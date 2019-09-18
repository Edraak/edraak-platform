"""
Helpers for the student app.
"""
import json
import logging
import mimetypes
import urllib
import urlparse
from datetime import datetime

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.urls import NoReverseMatch, reverse
from django.core.validators import ValidationError
from django.contrib.auth import load_backend
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import http
from django.utils.translation import ugettext as _
from oauth2_provider.models import AccessToken as dot_access_token
from oauth2_provider.models import RefreshToken as dot_refresh_token
from provider.oauth2.models import AccessToken as dop_access_token
from provider.oauth2.models import RefreshToken as dop_refresh_token
from pytz import UTC
from six import iteritems, text_type
import third_party_auth
from course_modes.models import CourseMode
from lms.djangoapps.certificates.api import (
    get_certificate_url,
    has_html_certificates_enabled
)
from lms.djangoapps.certificates.models import (
    CertificateStatuses,
    certificate_status_for_student
)
from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lms.djangoapps.verify_student.models import VerificationDeadline
from lms.djangoapps.verify_student.services import IDVerificationService
from lms.djangoapps.verify_student.utils import is_verification_expiring_soon, verification_for_datetime
from openedx.core.djangoapps.certificates.api import certificates_viewable_for_course
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from openedx.core.djangoapps.theming import helpers as theming_helpers
from openedx.core.djangoapps.theming.helpers import get_themes
from student.models import (
    LinkedInAddToProfileConfiguration,
    PasswordHistory,
    Registration,
    UserAttribute,
    UserProfile,
    unique_id_for_user,
    email_exists_or_retired
)


# Enumeration of per-course verification statuses
# we display on the student dashboard.
VERIFY_STATUS_NEED_TO_VERIFY = "verify_need_to_verify"
VERIFY_STATUS_SUBMITTED = "verify_submitted"
VERIFY_STATUS_RESUBMITTED = "re_verify_submitted"
VERIFY_STATUS_APPROVED = "verify_approved"
VERIFY_STATUS_MISSED_DEADLINE = "verify_missed_deadline"
VERIFY_STATUS_NEED_TO_REVERIFY = "verify_need_to_reverify"

DISABLE_UNENROLL_CERT_STATES = [
    'generating',
    'downloadable',
]
USERNAME_EXISTS_MSG_FMT = _("An account with the Public Username '{username}' already exists.")


log = logging.getLogger(__name__)


def check_verify_status_by_course(user, course_enrollments):
    """
    Determine the per-course verification statuses for a given user.

    The possible statuses are:
        * VERIFY_STATUS_NEED_TO_VERIFY: The student has not yet submitted photos for verification.
        * VERIFY_STATUS_SUBMITTED: The student has submitted photos for verification,
          but has have not yet been approved.
        * VERIFY_STATUS_RESUBMITTED: The student has re-submitted photos for re-verification while
          they still have an active but expiring ID verification
        * VERIFY_STATUS_APPROVED: The student has been successfully verified.
        * VERIFY_STATUS_MISSED_DEADLINE: The student did not submit photos within the course's deadline.
        * VERIFY_STATUS_NEED_TO_REVERIFY: The student has an active verification, but it is
            set to expire before the verification deadline for the course.

    It is is also possible that a course does NOT have a verification status if:
        * The user is not enrolled in a verified mode, meaning that the user didn't pay.
        * The course does not offer a verified mode.
        * The user submitted photos but an error occurred while verifying them.
        * The user submitted photos but the verification was denied.

    In the last two cases, we rely on messages in the sidebar rather than displaying
    messages for each course.

    Arguments:
        user (User): The currently logged-in user.
        course_enrollments (list[CourseEnrollment]): The courses the user is enrolled in.

    Returns:
        dict: Mapping of course keys verification status dictionaries.
            If no verification status is applicable to a course, it will not
            be included in the dictionary.
            The dictionaries have these keys:
                * status (str): One of the enumerated status codes.
                * days_until_deadline (int): Number of days until the verification deadline.
                * verification_good_until (str): Date string for the verification expiration date.

    """
    status_by_course = {}

    # Retrieve all verifications for the user, sorted in descending
    # order by submission datetime
    verifications = IDVerificationService.verifications_for_user(user)

    # Check whether the user has an active or pending verification attempt
    has_active_or_pending = IDVerificationService.user_has_valid_or_pending(user)

    # Retrieve expiration_datetime of most recent approved verification
    expiration_datetime = IDVerificationService.get_expiration_datetime(user, ['approved'])
    verification_expiring_soon = is_verification_expiring_soon(expiration_datetime)

    # Retrieve verification deadlines for the enrolled courses
    enrolled_course_keys = [enrollment.course_id for enrollment in course_enrollments]
    course_deadlines = VerificationDeadline.deadlines_for_courses(enrolled_course_keys)

    recent_verification_datetime = None

    for enrollment in course_enrollments:

        # If the user hasn't enrolled as verified, then the course
        # won't display state related to its verification status.
        if enrollment.mode in CourseMode.VERIFIED_MODES:

            # Retrieve the verification deadline associated with the course.
            # This could be None if the course doesn't have a deadline.
            deadline = course_deadlines.get(enrollment.course_id)

            relevant_verification = verification_for_datetime(deadline, verifications)

            # Picking the max verification datetime on each iteration only with approved status
            if relevant_verification is not None and relevant_verification.status == "approved":
                recent_verification_datetime = max(
                    recent_verification_datetime if recent_verification_datetime is not None
                    else relevant_verification.expiration_datetime,
                    relevant_verification.expiration_datetime
                )

            # By default, don't show any status related to verification
            status = None
            should_display = True

            # Check whether the user was approved or is awaiting approval
            if relevant_verification is not None:
                should_display = relevant_verification.should_display_status_to_user()

                if relevant_verification.status == "approved":
                    if verification_expiring_soon:
                        status = VERIFY_STATUS_NEED_TO_REVERIFY
                    else:
                        status = VERIFY_STATUS_APPROVED
                elif relevant_verification.status == "submitted":
                    if verification_expiring_soon:
                        status = VERIFY_STATUS_RESUBMITTED
                    else:
                        status = VERIFY_STATUS_SUBMITTED

            # If the user didn't submit at all, then tell them they need to verify
            # If the deadline has already passed, then tell them they missed it.
            # If they submitted but something went wrong (error or denied),
            # then don't show any messaging next to the course, since we already
            # show messages related to this on the left sidebar.
            submitted = (
                relevant_verification is not None and
                relevant_verification.status not in ["created", "ready"]
            )
            if status is None and not submitted:
                if deadline is None or deadline > datetime.now(UTC):
                    if IDVerificationService.user_is_verified(user) and verification_expiring_soon:
                        # The user has an active verification, but the verification
                        # is set to expire within "EXPIRING_SOON_WINDOW" days (default is 4 weeks).
                        # Tell the student to reverify.
                        status = VERIFY_STATUS_NEED_TO_REVERIFY
                    elif not IDVerificationService.user_is_verified(user):
                        status = VERIFY_STATUS_NEED_TO_VERIFY
                else:
                    # If a user currently has an active or pending verification,
                    # then they may have submitted an additional attempt after
                    # the verification deadline passed.  This can occur,
                    # for example, when the support team asks a student
                    # to reverify after the deadline so they can receive
                    # a verified certificate.
                    # In this case, we still want to show them as "verified"
                    # on the dashboard.
                    if has_active_or_pending:
                        status = VERIFY_STATUS_APPROVED

                    # Otherwise, the student missed the deadline, so show
                    # them as "honor" (the kind of certificate they will receive).
                    else:
                        status = VERIFY_STATUS_MISSED_DEADLINE

            # Set the status for the course only if we're displaying some kind of message
            # Otherwise, leave the course out of the dictionary.
            if status is not None:
                days_until_deadline = None

                now = datetime.now(UTC)
                if deadline is not None and deadline > now:
                    days_until_deadline = (deadline - now).days

                status_by_course[enrollment.course_id] = {
                    'status': status,
                    'days_until_deadline': days_until_deadline,
                    'should_display': should_display,
                }

    if recent_verification_datetime:
        for key, value in iteritems(status_by_course):  # pylint: disable=unused-variable
            status_by_course[key]['verification_good_until'] = recent_verification_datetime.strftime("%m/%d/%Y")

    return status_by_course


def auth_pipeline_urls(auth_entry, redirect_url=None):
    """Retrieve URLs for each enabled third-party auth provider.

    These URLs are used on the "sign up" and "sign in" buttons
    on the login/registration forms to allow users to begin
    authentication with a third-party provider.

    Optionally, we can redirect the user to an arbitrary
    url after auth completes successfully.  We use this
    to redirect the user to a page that required login,
    or to send users to the payment flow when enrolling
    in a course.

    Args:
        auth_entry (string): Either `pipeline.AUTH_ENTRY_LOGIN` or `pipeline.AUTH_ENTRY_REGISTER`

    Keyword Args:
        redirect_url (unicode): If provided, send users to this URL
            after they successfully authenticate.

    Returns:
        dict mapping provider IDs to URLs

    """
    if not third_party_auth.is_enabled():
        return {}

    return {
        provider.provider_id: third_party_auth.pipeline.get_login_url(
            provider.provider_id, auth_entry, redirect_url=redirect_url
        ) for provider in third_party_auth.provider.Registry.displayed_for_login()
    }


# Query string parameters that can be passed to the "finish_auth" view to manage
# things like auto-enrollment.
POST_AUTH_PARAMS = ('course_id', 'enrollment_action', 'course_mode', 'email_opt_in', 'purchase_workflow')


def get_next_url_for_login_page(request):
    """
    Determine the URL to redirect to following login/registration/third_party_auth

    The user is currently on a login or registration page.
    If 'course_id' is set, or other POST_AUTH_PARAMS, we will need to send the user to the
    /account/finish_auth/ view following login, which will take care of auto-enrollment in
    the specified course.

    Otherwise, we go to the ?next= query param or to the dashboard if nothing else is
    specified.

    If THIRD_PARTY_AUTH_HINT is set, then `tpa_hint=<hint>` is added as a query parameter.
    """
    redirect_to = get_redirect_to(request)
    if not redirect_to:
        try:
            redirect_to = reverse('dashboard')
        except NoReverseMatch:
            redirect_to = reverse('home')

    if any(param in request.GET for param in POST_AUTH_PARAMS):
        # Before we redirect to next/dashboard, we need to handle auto-enrollment:
        params = [(param, request.GET[param]) for param in POST_AUTH_PARAMS if param in request.GET]
        params.append(('next', redirect_to))  # After auto-enrollment, user will be sent to payment page or to this URL
        redirect_to = '{}?{}'.format(reverse('finish_auth'), urllib.urlencode(params))
        # Note: if we are resuming a third party auth pipeline, then the next URL will already
        # be saved in the session as part of the pipeline state. That URL will take priority
        # over this one.

    # Append a tpa_hint query parameter, if one is configured
    tpa_hint = configuration_helpers.get_value(
        "THIRD_PARTY_AUTH_HINT",
        settings.FEATURES.get("THIRD_PARTY_AUTH_HINT", '')
    )
    if tpa_hint:
        # Don't add tpa_hint if we're already in the TPA pipeline (prevent infinite loop),
        # and don't overwrite any existing tpa_hint params (allow tpa_hint override).
        running_pipeline = third_party_auth.pipeline.get(request)
        (scheme, netloc, path, query, fragment) = list(urlparse.urlsplit(redirect_to))
        if not running_pipeline and 'tpa_hint' not in query:
            params = urlparse.parse_qs(query)
            params['tpa_hint'] = [tpa_hint]
            query = urllib.urlencode(params, doseq=True)
            redirect_to = urlparse.urlunsplit((scheme, netloc, path, query, fragment))

    return redirect_to


def get_next_url_for_progs_login_page(request, initial_mode):
    """
    Determine the URL to redirect to following login/registration/third_party_auth
    The user is currently on a login or reigration page.
    If 'course_id' is set, or other POST_AUTH_PARAMS, we will need to send the user to the
    /account/finish_auth/ view following login, which will take care of auto-enrollment in
    the specified course.
    Otherwise, we go to the ?next= query param or to the dashboard if nothing else is
    specified.
    """
    params = []
    next = request.GET.get('next', None)

    if next:
        params.append(('next', next))

    if any(param in request.GET for param in POST_AUTH_PARAMS):
        # Before we redirect to next/dashboard, we need to handle auto-enrollment:
        params += [(param, request.GET[param]) for param in POST_AUTH_PARAMS if param in request.GET]
        # After auto-enrollment, user will be sent to payment page or to this URL
        # Note: if we are resuming a third party auth pipeline, then the next URL will already
        # be saved in the session as part of the pipeline state. That URL will take priority
        # over this one.

    from course_modes.edraak_helpers import get_progs_url

    auth_url = get_progs_url(initial_mode)

    if params:
        redirect_to = '{}?{}'.format(auth_url, urllib.urlencode(params))
    else:
        redirect_to = auth_url

    return redirect_to


def get_redirect_to(request):
    """
    Determine the redirect url and return if safe
    :argument
        request: request object

    :returns: redirect url if safe else None
    """
    redirect_to = request.GET.get('next')
    header_accept = request.META.get('HTTP_ACCEPT', '')

    # If we get a redirect parameter, make sure it's safe i.e. not redirecting outside our domain.
    # Also make sure that it is not redirecting to a static asset and redirected page is web page
    # not a static file. As allowing assets to be pointed to by "next" allows 3rd party sites to
    # get information about a user on edx.org. In any such case drop the parameter.
    if redirect_to:
        mime_type, _ = mimetypes.guess_type(redirect_to, strict=False)
        if not http.is_safe_url(redirect_to, allowed_hosts={request.get_host()}, require_https=True):
            log.warning(
                u'Unsafe redirect parameter detected after login page: %(redirect_to)r',
                {"redirect_to": redirect_to}
            )
            redirect_to = None
        elif 'text/html' not in header_accept:
            log.info(
                u'Redirect to non html content %(content_type)r detected from %(user_agent)r'
                u' after login page: %(redirect_to)r',
                {
                    "redirect_to": redirect_to, "content_type": header_accept,
                    "user_agent": request.META.get('HTTP_USER_AGENT', '')
                }
            )
            redirect_to = None
        elif mime_type:
            log.warning(
                u'Redirect to url path with specified filed type %(mime_type)r not allowed: %(redirect_to)r',
                {"redirect_to": redirect_to, "mime_type": mime_type}
            )
            redirect_to = None
        elif settings.STATIC_URL in redirect_to:
            log.warning(
                u'Redirect to static content detected after login page: %(redirect_to)r',
                {"redirect_to": redirect_to}
            )
            redirect_to = None
        else:
            themes = get_themes()
            next_path = urlparse.urlparse(redirect_to).path
            for theme in themes:
                if theme.theme_dir_name in next_path:
                    log.warning(
                        u'Redirect to theme content detected after login page: %(redirect_to)r',
                        {"redirect_to": redirect_to}
                    )
                    redirect_to = None
                    break

    return redirect_to


def destroy_oauth_tokens(user):
    """
    Destroys ALL OAuth access and refresh tokens for the given user.
    """
    dop_access_token.objects.filter(user=user.id).delete()
    dop_refresh_token.objects.filter(user=user.id).delete()
    dot_access_token.objects.filter(user=user.id).delete()
    dot_refresh_token.objects.filter(user=user.id).delete()


def generate_activation_email_context(user, registration):
    """
    Constructs a dictionary for use in activation email contexts

    Arguments:
        user (User): Currently logged-in user
        registration (Registration): Registration object for the currently logged-in user
    """
    return {
        'name': user.profile.name,
        'key': registration.activation_key,
        'lms_url': configuration_helpers.get_value('LMS_ROOT_URL', settings.LMS_ROOT_URL),
        'platform_name': configuration_helpers.get_value('PLATFORM_NAME', settings.PLATFORM_NAME),
        'support_url': configuration_helpers.get_value('SUPPORT_SITE_LINK', settings.SUPPORT_SITE_LINK),
        'support_email': configuration_helpers.get_value('CONTACT_EMAIL', settings.CONTACT_EMAIL),
    }


def create_or_set_user_attribute_created_on_site(user, site):
    """
    Create or Set UserAttribute indicating the microsite site the user account was created on.
    User maybe created on 'courses.edx.org', or a white-label site. Due to the very high
    traffic on this table we now ignore the default site (eg. 'courses.edx.org') and
    code which comsumes this attribute should assume a 'created_on_site' which doesn't exist
    belongs to the default site.
    """
    if site and site.id != settings.SITE_ID:
        UserAttribute.set_user_attribute(user, 'created_on_site', site.domain)


# We want to allow inactive users to log in only when their account is first created
NEW_USER_AUTH_BACKEND = 'django.contrib.auth.backends.AllowAllUsersModelBackend'

# Disable this warning because it doesn't make sense to completely refactor tests to appease Pylint
# pylint: disable=logging-format-interpolation


def authenticate_new_user(request, username, password):
    """
    Immediately after a user creates an account, we log them in. They are only
    logged in until they close the browser. They can't log in again until they click
    the activation link from the email.
    """
    backend = load_backend(NEW_USER_AUTH_BACKEND)
    user = backend.authenticate(request=request, username=username, password=password)
    user.backend = NEW_USER_AUTH_BACKEND
    return user


class AccountValidationError(Exception):
    """
    Used in account creation views to raise exceptions with details about specific invalid fields
    """
    def __init__(self, message, field):
        super(AccountValidationError, self).__init__(message)
        self.field = field


def cert_info(user, course_overview):
    """
    Get the certificate info needed to render the dashboard section for the given
    student and course.

    Arguments:
        user (User): A user.
        course_overview (CourseOverview): A course.

    Returns:
        dict: A dictionary with keys:
            'status': one of 'generating', 'downloadable', 'notpassing', 'processing', 'restricted', 'unavailable', or
                'certificate_earned_but_not_available'
            'download_url': url, only present if show_download_url is True
            'show_survey_button': bool
            'survey_url': url, only if show_survey_button is True
            'grade': if status is not 'processing'
            'can_unenroll': if status allows for unenrollment
    """
    return _cert_info(
        user,
        course_overview,
        certificate_status_for_student(user, course_overview.id)
    )


def _cert_info(user, course_overview, cert_status):
    """
    Implements the logic for cert_info -- split out for testing.

    Arguments:
        user (User): A user.
        course_overview (CourseOverview): A course.
    """
    # simplify the status for the template using this lookup table
    template_state = {
        CertificateStatuses.generating: 'generating',
        CertificateStatuses.downloadable: 'downloadable',
        CertificateStatuses.notpassing: 'notpassing',
        CertificateStatuses.restricted: 'restricted',
        CertificateStatuses.auditing: 'auditing',
        CertificateStatuses.audit_passing: 'auditing',
        CertificateStatuses.audit_notpassing: 'auditing',
        CertificateStatuses.unverified: 'unverified',
    }

    certificate_earned_but_not_available_status = 'certificate_earned_but_not_available'
    default_status = 'processing'

    default_info = {
        'status': default_status,
        'show_survey_button': False,
        'can_unenroll': True,
    }

    if cert_status is None:
        return default_info

    status = template_state.get(cert_status['status'], default_status)
    is_hidden_status = status in ('unavailable', 'processing', 'generating', 'notpassing', 'auditing')

    if (
        not certificates_viewable_for_course(course_overview) and
        (status in CertificateStatuses.PASSED_STATUSES) and
        course_overview.certificate_available_date
    ):
        status = certificate_earned_but_not_available_status

    if (
        course_overview.certificates_display_behavior == 'early_no_info' and
        is_hidden_status
    ):
        return default_info

    status_dict = {
        'status': status,
        'mode': cert_status.get('mode', None),
        'linked_in_url': None,
        'can_unenroll': status not in DISABLE_UNENROLL_CERT_STATES,
    }

    if status != default_status and course_overview.end_of_course_survey_url is not None:
        status_dict.update({
            'show_survey_button': True,
            'survey_url': process_survey_link(course_overview.end_of_course_survey_url, user)})
    else:
        status_dict['show_survey_button'] = False

    if status == 'downloadable':
        # showing the certificate web view button if certificate is downloadable state and feature flags are enabled.
        if has_html_certificates_enabled(course_overview):
            if course_overview.has_any_active_web_certificate:
                status_dict.update({
                    'show_cert_web_view': True,
                    'cert_web_view_url': get_certificate_url(course_id=course_overview.id, uuid=cert_status['uuid'])
                })
            else:
                # don't show download certificate button if we don't have an active certificate for course
                status_dict['status'] = 'unavailable'
        elif 'download_url' not in cert_status:
            log.warning(
                u"User %s has a downloadable cert for %s, but no download url",
                user.username,
                course_overview.id
            )
            return default_info
        else:
            status_dict['download_url'] = cert_status['download_url']

            # If enabled, show the LinkedIn "add to profile" button
            # Clicking this button sends the user to LinkedIn where they
            # can add the certificate information to their profile.
            linkedin_config = LinkedInAddToProfileConfiguration.current()

            # posting certificates to LinkedIn is not currently
            # supported in White Labels
            if linkedin_config.enabled and not theming_helpers.is_request_in_themed_site():
                status_dict['linked_in_url'] = linkedin_config.add_to_profile_url(
                    course_overview.id,
                    course_overview.display_name,
                    cert_status.get('mode'),
                    cert_status['download_url']
                )

    if status in {'generating', 'downloadable', 'notpassing', 'restricted', 'auditing', 'unverified'}:
        cert_grade_percent = -1
        persisted_grade_percent = -1
        persisted_grade = CourseGradeFactory().read(user, course=course_overview, create_if_needed=False)
        if persisted_grade is not None:
            persisted_grade_percent = persisted_grade.percent

        if 'grade' in cert_status:
            cert_grade_percent = float(cert_status['grade'])

        if cert_grade_percent == -1 and persisted_grade_percent == -1:
            # Note: as of 11/20/2012, we know there are students in this state-- cs169.1x,
            # who need to be regraded (we weren't tracking 'notpassing' at first).
            # We can add a log.warning here once we think it shouldn't happen.
            return default_info

        status_dict['grade'] = text_type(max(cert_grade_percent, persisted_grade_percent))

    return status_dict


def process_survey_link(survey_link, user):
    """
    If {UNIQUE_ID} appears in the link, replace it with a unique id for the user.
    Currently, this is sha1(user.username).  Otherwise, return survey_link.
    """
    return survey_link.format(UNIQUE_ID=unique_id_for_user(user))


def do_create_account(form, custom_form=None):
    """
    Given cleaned post variables, create the User and UserProfile objects, as well as the
    registration for this user.

    Returns a tuple (User, UserProfile, Registration).

    Note: this function is also used for creating test users.
    """
    # Check if ALLOW_PUBLIC_ACCOUNT_CREATION flag turned off to restrict user account creation
    if not configuration_helpers.get_value(
            'ALLOW_PUBLIC_ACCOUNT_CREATION',
            settings.FEATURES.get('ALLOW_PUBLIC_ACCOUNT_CREATION', True)
    ):
        raise PermissionDenied()

    errors = {}
    errors.update(form.errors)
    if custom_form:
        errors.update(custom_form.errors)

    if errors:
        raise ValidationError(errors)

    proposed_username = form.cleaned_data["username"]
    user = User(
        username=proposed_username,
        email=form.cleaned_data["email"],
        is_active=False
    )
    user.set_password(form.cleaned_data["password"])
    registration = Registration()

    # TODO: Rearrange so that if part of the process fails, the whole process fails.
    # Right now, we can have e.g. no registration e-mail sent out and a zombie account
    try:
        with transaction.atomic():
            user.save()
            if custom_form:
                custom_model = custom_form.save(commit=False)
                custom_model.user = user
                custom_model.save()
    except IntegrityError:
        # Figure out the cause of the integrity error
        # TODO duplicate email is already handled by form.errors above as a ValidationError.
        # The checks for duplicate email/username should occur in the same place with an
        # AccountValidationError and a consistent user message returned (i.e. both should
        # return "It looks like {username} belongs to an existing account. Try again with a
        # different username.")
        if User.objects.filter(username=user.username):
            raise AccountValidationError(
                USERNAME_EXISTS_MSG_FMT.format(username=proposed_username),
                field="username"
            )
        elif email_exists_or_retired(user.email):
            raise AccountValidationError(
                _("An account with the Email '{email}' already exists.").format(email=user.email),
                field="email"
            )
        else:
            raise

    # add this account creation to password history
    # NOTE, this will be a NOP unless the feature has been turned on in configuration
    password_history_entry = PasswordHistory()
    password_history_entry.create(user)

    registration.register(user)

    profile_fields = [
        "name", "level_of_education", "gender", "mailing_address", "city", "country", "goals",
        "year_of_birth"
    ]
    profile = UserProfile(
        user=user,
        **{key: form.cleaned_data.get(key) for key in profile_fields}
    )
    extended_profile = form.cleaned_extended_profile
    if extended_profile:
        profile.meta = json.dumps(extended_profile)
    try:
        profile.save()
    except Exception:
        log.exception("UserProfile creation failed for user {id}.".format(id=user.id))
        raise

    return user, profile, registration
