"""HTTP end-points for the User API. """

import logging
import jwt

from django.contrib.auth.models import User
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.db import transaction
from django.conf import settings
from django.db.utils import DatabaseError
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext as _
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST
from django_filters.rest_framework import DjangoFilterBackend
from opaque_keys import InvalidKeyError
from opaque_keys.edx import locator
from opaque_keys.edx.keys import CourseKey
from rest_framework import authentication, generics, status, viewsets
from rest_framework.exceptions import ParseError
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from six import text_type

import accounts
from django_comment_common.models import Role
from openedx.core.djangoapps.user_api.accounts.api import check_account_exists
from openedx.core.djangoapps.user_api.api import (
    RegistrationFormFactory,
    get_login_session_form,
    get_password_reset_form
)
from openedx.core.djangoapps.user_api.helpers import (
    require_post_params,
    require_any_post_params,
    shim_student_view
)
from openedx.core.djangoapps.user_api.models import UserPreference
from student.models import UserProfile
from openedx.core.djangoapps.user_api.preferences.api import get_country_time_zones, update_email_opt_in
from openedx.core.djangoapps.user_api.serializers import CountryTimeZoneSerializer, UserPreferenceSerializer, UserSerializer
from openedx.core.lib.api.authentication import SessionAuthenticationAllowInactiveUser
from openedx.core.lib.api.permissions import ApiKeyHeaderPermission
from student.cookies import set_logged_in_cookies
from student.views import AccountValidationError, create_account_with_params
from util.db import outer_atomic
from util.json_request import JsonResponse

log = logging.getLogger(__name__)


class LoginSessionView(APIView):
    """HTTP end-points for logging in users. """

    # This end-point is available to anonymous users,
    # so do not require authentication.
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return HttpResponse(get_login_session_form(request).to_json(), content_type="application/json")

    @method_decorator(require_any_post_params([["email", "password"], ["data_token"]]))
    @method_decorator(csrf_protect)
    def post(self, request):
        """Log in a user.

        You must send all required form fields with the request.

        You can optionally send an `analytics` param with a JSON-encoded
        object with additional info to include in the login analytics event.
        Currently, the only supported field is "enroll_course_id" to indicate
        that the user logged in while enrolling in a particular course.

        Arguments:
            request (HttpRequest)

        Returns:
            HttpResponse: 200 on success
            HttpResponse: 400 if the request is not valid.
            HttpResponse: 403 if authentication failed.
                403 with content "third-party-auth" if the user
                has successfully authenticated with a third party provider
                but does not have a linked account.
            HttpResponse: 302 if redirecting to another page.

        Example Usage:

            POST /user_api/v1/login_session
            with POST params `email`, `password`, and `remember`.

            200 OK

        """
        # For the initial implementation, shim the existing login view
        # from the student Django app.
        from student.views import login_user
        return shim_student_view(login_user, check_logged_in=True)(request)

    @method_decorator(sensitive_post_parameters("password"))
    def dispatch(self, request, *args, **kwargs):
        return super(LoginSessionView, self).dispatch(request, *args, **kwargs)


class RegistrationView(APIView):
    """HTTP end-points for creating a new user. """

    # This end-point is available to anonymous users,
    # so do not require authentication.
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return HttpResponse(RegistrationFormFactory().get_registration_form(request).to_json(),
                            content_type="application/json")

    @method_decorator(csrf_exempt)
    def post(self, request):
        """Create the user's account.

        You must send all required form fields with the request.

        You can optionally send a "course_id" param to indicate in analytics
        events that the user registered while enrolling in a particular course.

        Arguments:
            request (HTTPRequest)

        Returns:
            HttpResponse: 200 on success
            HttpResponse: 400 if the request is not valid.
            HttpResponse: 409 if an account with the given username or email
                address already exists
            HttpResponse: 403 operation not allowed
        """
        data = request.POST.copy()

        # Decrypt form data if it is encrypted
        if 'data_token' in request.POST:
            data_token = request.POST.get('data_token')

            try:
                decoded_data = jwt.decode(data_token,
                                          settings.EDRAAK_LOGISTRATION_SECRET_KEY,
                                          verify=False,
                                          algorithms=[settings.EDRAAK_LOGISTRATION_SIGNING_ALGORITHM])
                data.update(decoded_data)

            except jwt.ExpiredSignatureError:
                err_msg = u"The provided data_token has been expired"
                log.warning(err_msg)

                return JsonResponse({
                    "success": False,
                    "value": err_msg,
                }, status=400)

            except jwt.DecodeError:
                err_msg = u"Signature verification failed"
                log.warning(err_msg)

                return JsonResponse({
                    "success": False,
                    "value": err_msg,
                }, status=400)

            except (jwt.InvalidTokenError, ValueError):
                err_msg = u"Invalid token"
                log.warning(err_msg)

                return JsonResponse({
                    "success": False,
                    "value": err_msg,
                }, status=400)

        email = data.get('email')
        username = data.get('username')

        # Handle duplicate email/username
        conflicts = check_account_exists(email=email, username=username)
        if conflicts:
            conflict_messages = {
                "email": accounts.EMAIL_CONFLICT_MSG.format(email_address=email),
                "username": accounts.USERNAME_CONFLICT_MSG.format(username=username),
            }
            errors = {
                field: [{"user_message": conflict_messages[field]}]
                for field in conflicts
            }
            return JsonResponse(errors, status=409)

        # Backwards compatibility: the student view expects both
        # terms of service and honor code values.  Since we're combining
        # these into a single checkbox, the only value we may get
        # from the new view is "honor_code".
        # Longer term, we will need to make this more flexible to support
        # open source installations that may have separate checkboxes
        # for TOS, privacy policy, etc.
        if data.get("honor_code") and "terms_of_service" not in data:
            data["terms_of_service"] = data["honor_code"]

        try:
            user = create_account_with_params(request, data)
        except AccountValidationError as err:
            errors = {
                err.field: [{"user_message": text_type(err)}]
            }
            return JsonResponse(errors, status=409)
        except ValidationError as err:
            # Should only get non-field errors from this function
            assert NON_FIELD_ERRORS not in err.message_dict
            # Only return first error for each field
            errors = {
                field: [{"user_message": error} for error in error_list]
                for field, error_list in err.message_dict.items()
            }
            return JsonResponse(errors, status=400)
        except PermissionDenied:
            return HttpResponseForbidden(_("Account creation not allowed."))

        response = JsonResponse({"success": True})
        set_logged_in_cookies(request, response, user)
        return response

    @method_decorator(transaction.non_atomic_requests)
    @method_decorator(sensitive_post_parameters("password"))
    def dispatch(self, request, *args, **kwargs):
        return super(RegistrationView, self).dispatch(request, *args, **kwargs)


@transaction.non_atomic_requests
@require_POST
@outer_atomic(read_committed=True)
def update_profile_info(request):
    """
    """
    # Get the user

    data = request.POST.copy()
    user = request.user

    post_registration_fields = [('gender', str), ('country', str), ('year_of_birth', int)]

    try:
        user_profile = UserProfile.objects.get(user=user)
        user_has_profile = True
    except UserProfile.DoesNotExist:
        # Handle when no profile for the user, create a new one
        user_profile = UserProfile(user=user)
        user_has_profile = False

    for field in post_registration_fields:
        field_name = field[0]
        field_type = field[1]

        value = field_type(data.get(field_name))

        if value:
            setattr(user_profile, field_name, value)

    try:
        user_profile.save(update_fields=list(field[0] for field in post_registration_fields) if user_has_profile else None)
        return JsonResponse({"is_success": True}, status=200)
    except (DatabaseError, ValidationError, TypeError) as e:
        log.error('Failed to save post auth data for {user}, exception is {e}'.format(user=user.username, e=e))

    return JsonResponse({"is_success": False}, status=400)


class PasswordResetView(APIView):
    """HTTP end-point for GETting a description of the password reset form. """

    # This end-point is available to anonymous users,
    # so do not require authentication.
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return HttpResponse(get_password_reset_form().to_json(), content_type="application/json")


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    DRF class for interacting with the User ORM object
    """
    authentication_classes = (authentication.SessionAuthentication,)
    permission_classes = (ApiKeyHeaderPermission,)
    queryset = User.objects.all().prefetch_related("preferences").select_related("profile")
    serializer_class = UserSerializer
    paginate_by = 10
    paginate_by_param = "page_size"


class ForumRoleUsersListView(generics.ListAPIView):
    """
    Forum roles are represented by a list of user dicts
    """
    authentication_classes = (authentication.SessionAuthentication,)
    permission_classes = (ApiKeyHeaderPermission,)
    serializer_class = UserSerializer
    paginate_by = 10
    paginate_by_param = "page_size"

    def get_queryset(self):
        """
        Return a list of users with the specified role/course pair
        """
        name = self.kwargs['name']
        course_id_string = self.request.query_params.get('course_id')
        if not course_id_string:
            raise ParseError('course_id must be specified')
        course_id = CourseKey.from_string(course_id_string)
        role = Role.objects.get_or_create(course_id=course_id, name=name)[0]
        users = role.users.prefetch_related("preferences").select_related("profile").all()
        return users


class UserPreferenceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    DRF class for interacting with the UserPreference ORM
    """
    authentication_classes = (authentication.SessionAuthentication,)
    permission_classes = (ApiKeyHeaderPermission,)
    queryset = UserPreference.objects.all()
    filter_backends = (DjangoFilterBackend,)
    filter_fields = ("key", "user")
    serializer_class = UserPreferenceSerializer
    paginate_by = 10
    paginate_by_param = "page_size"


class PreferenceUsersListView(generics.ListAPIView):
    """
    DRF class for listing a user's preferences
    """
    authentication_classes = (authentication.SessionAuthentication,)
    permission_classes = (ApiKeyHeaderPermission,)
    serializer_class = UserSerializer
    paginate_by = 10
    paginate_by_param = "page_size"

    def get_queryset(self):
        return User.objects.filter(
            preferences__key=self.kwargs["pref_key"]
        ).prefetch_related("preferences").select_related("profile")


class UpdateEmailOptInPreference(APIView):
    """View for updating the email opt in preference. """
    authentication_classes = (SessionAuthenticationAllowInactiveUser,)
    permission_classes = (IsAuthenticated,)

    @method_decorator(require_post_params(["course_id", "email_opt_in"]))
    @method_decorator(ensure_csrf_cookie)
    def post(self, request):
        """ Post function for updating the email opt in preference.

        Allows the modification or creation of the email opt in preference at an
        organizational level.

        Args:
            request (Request): The request should contain the following POST parameters:
                * course_id: The slash separated course ID. Used to determine the organization
                    for this preference setting.
                * email_opt_in: "True" or "False" to determine if the user is opting in for emails from
                    this organization. If the string does not match "True" (case insensitive) it will
                    assume False.

        """
        course_id = request.data['course_id']
        try:
            org = locator.CourseLocator.from_string(course_id).org
        except InvalidKeyError:
            return HttpResponse(
                status=400,
                content="No course '{course_id}' found".format(course_id=course_id),
                content_type="text/plain"
            )
        # Only check for true. All other values are False.
        email_opt_in = request.data['email_opt_in'].lower() == 'true'
        update_email_opt_in(request.user, org, email_opt_in)
        return HttpResponse(status=status.HTTP_200_OK)


class CountryTimeZoneListView(generics.ListAPIView):
    """
    **Use Cases**

        Retrieves a list of all time zones, by default, or common time zones for country, if given

        The country is passed in as its ISO 3166-1 Alpha-2 country code as an
        optional 'country_code' argument. The country code is also case-insensitive.

    **Example Requests**

        GET /user_api/v1/preferences/time_zones/

        GET /user_api/v1/preferences/time_zones/?country_code=FR

    **Example GET Response**

        If the request is successful, an HTTP 200 "OK" response is returned along with a
        list of time zone dictionaries for all time zones or just for time zones commonly
        used in a country, if given.

        Each time zone dictionary contains the following values.

            * time_zone: The name of the time zone.
            * description: The display version of the time zone
    """
    serializer_class = CountryTimeZoneSerializer
    paginator = None

    def get_queryset(self):
        country_code = self.request.GET.get('country_code', None)
        return get_country_time_zones(country_code)
