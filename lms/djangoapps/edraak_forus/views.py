"""
The views in this module mimics the `student.views` registration form and API.
This is useful to enable so much code reuse.
"""

import logging
import json
from urllib import urlencode

from django.conf import settings
from django.core.urlresolvers import reverse
from django.shortcuts import redirect
from django.contrib.auth import logout, login
from django.contrib.auth.models import User
from django.utils.translation import ugettext as _
from opaque_keys.edx.locations import SlashSeparatedCourseKey
from util.json_request import JsonResponse

from student_account.views import _local_server_get
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from student.cookies import delete_logged_in_cookies

from edxmako.shortcuts import render_to_response
from third_party_auth import pipeline
from django.views.generic import View

from openedx.core.djangoapps.user_api.preferences.api import set_user_preference
from lang_pref import LANGUAGE_KEY

from xmodule.modulestore.django import modulestore

from django.utils.translation import LANGUAGE_SESSION_KEY

from student.models import AlreadyEnrolledError
from student.helpers import enroll, get_next_url_for_login_page, InvalidCourseIdError

from openedx.core.djangoapps.user_api.views import RegistrationView

from course_modes.helpers import SUCCESS_ENROLL_PAGE, get_mktg_for_course

from .models import ForusProfile
from .helpers import validate_forus_params, forus_error_redirect, is_enabled_language

log = logging.getLogger(__name__)


# New fields that are specific to ForUs form
FORUS_SPECIFIC_FIELDS = (
    'course_id',
    'enrollment_action',
    'forus_hmac',
    'lang',
    'time',
)

# Fields that would be populated with ForUs params
POPULATED_FIELDS = FORUS_SPECIFIC_FIELDS + (
    'country',
    'email',
    'gender',
    'level_of_education',
    'name',
    'year_of_birth',
)

HIDDEN_FIELDS = POPULATED_FIELDS + (
    'goals',  # Hide goals because the ForUs people didn't like to
              # ask their students about their goals in Edraak.
    'password',
)


class AuthView(View):
    def get(self, request):
        try:
            forus_params = validate_forus_params(request.GET)
        except ValidationError as e:
            return forus_error_redirect(*e.messages)

        course_string_id = forus_params['course_id']
        course_key = SlashSeparatedCourseKey.from_deprecated_string(course_string_id)

        if request.user.is_authenticated() and request.user.email != forus_params['email']:
            logout(request)
            return redirect(request.get_full_path())

        try:
            user = User.objects.get(email=forus_params['email'])
            # Simulate `django.contrib.auth.authenticate()` function
            if not request.user.is_authenticated():
                if ForusProfile.is_forus_user(user):
                    user.backend = settings.AUTHENTICATION_BACKENDS[0]
                    login(request, user)
                else:
                    # Redirect the non-forus users to the login page
                    return redirect('{login_url}?{params}'.format(
                            login_url=reverse('signin_user'),
                            params=urlencode({
                                'course_id': course_string_id,
                                'enrollment_action': 'enroll',
                            }),
                    ))

            return self.enroll(request, user, course_key)
        except User.DoesNotExist:
            return self.render_auth_form(request, forus_params)

    def enroll(self, request, user, course_key):
        try:
            enroll(user, course_key, request, check_access=True)
            course_url = get_mktg_for_course(SUCCESS_ENROLL_PAGE, unicode(course_key))
            return redirect(course_url)
        except AlreadyEnrolledError:
            course = modulestore().get_course(course_key)
            if course.has_started():
                return redirect('course_root', unicode(course_key))
            else:
                return redirect('dashboard')
        except InvalidCourseIdError:
            return forus_error_redirect(_("Invalid course id"))
        except Exception as e:
            log.exception(e)
            return forus_error_redirect(_("Could not enroll"))

    def get_registration_form_description(self, request, forus_params):
        """Retrieve form descriptions from the user API.

        Arguments:
            request (HttpRequest): The original request, used to retrieve session info.
            forus_params (dict): forus params values.

        Returns:
            JSON-serialized registration form descriptions.

        """
        form = json.loads(_local_server_get(reverse('forus_v1_reg_api'), request.session))

        for field in form['fields']:
            field_name = field['name']

            if field_name in POPULATED_FIELDS:
                    field['defaultValue'] = forus_params[field_name]

            if 'username' == field_name:
                field['defaultValue'] = forus_params['name'].strip()

        return form

    def render_auth_form(self, request, forus_params):
        """Render the combined login/registration form, defaulting to login

        This relies on the JS to asynchronously load the actual form from
        the user_api.
        """
        initial_mode = 'register'

        # Determine the URL to redirect to following login/registration/third_party_auth
        redirect_to = get_next_url_for_login_page(request)

        # If we're already logged in, redirect to the dashboard
        if request.user.is_authenticated():
            logout(request)
            delete_logged_in_cookies(request)
            return redirect(redirect_to)

        # Otherwise, render the combined login/registration page
        context = {
            'data': {
                'login_redirect_url': redirect_to,
                'initial_mode': initial_mode,
                'third_party_auth': {},
                'third_party_auth_hint': '',
                'platform_name': settings.PLATFORM_NAME,

                # Include form descriptions retrieved from the user API.
                # We could have the JS client make these requests directly,
                # but we include them in the initial page load to avoid
                # the additional round-trip to the server.
                'registration_form_desc': self.get_registration_form_description(request, forus_params),
            },
            'login_redirect_url': redirect_to,  # This gets added to the query string of the "Sign In" button in header
            'responsive': True,
            'allow_iframing': True,
            'disable_courseware_js': True,
            'disable_footer': True,
        }

        return render_to_response('edraak_forus/auth.html', context)

    def dispatch(self, request, *args, **kwargs):
        url_lang = request.GET.get('lang')

        if is_enabled_language(url_lang):
            if LANGUAGE_SESSION_KEY not in request.session:
                request.session[LANGUAGE_SESSION_KEY] = url_lang

        return super(AuthView, self).dispatch(request, *args, **kwargs)


class RegistrationApiView(RegistrationView):
    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        response = super(RegistrationApiView, self).get(request)
        registration_form = json.loads(response.content)

        for field_name in FORUS_SPECIFIC_FIELDS:
            registration_form['fields'].append({
                'name': field_name,

                # Make it ran
                'required': True,
                'errorMessages': {},
                'restrictions': {},
                'form': 'register',
                'placeholder': '',
            })

        registration_form['submit_url'] = reverse('forus_v1_reg_api')

        for field in registration_form['fields']:
            field_name = field['name']

            if field_name in HIDDEN_FIELDS:
                field.update({
                    'instructions': '',
                    'label': '',
                    'requiredStr': '*',
                    'type': 'hidden',
                })

            if 'password' == field_name:
                field['defaultValue'] = pipeline.make_random_password()

        return JsonResponse(registration_form)

    @method_decorator(csrf_exempt)
    def post(self, request):
        try:
            validate_forus_params(request.POST)
        except ValidationError as e:
            errors = {
                field: [
                    {"user_message": exp.messages[0]}
                ] for field, exp in e.message_dict.iteritems()
            }
            return JsonResponse(errors, status=400)

        response = super(RegistrationApiView, self).post(request)

        if 200 == response.status_code:
            self.handle_sucessfull_register(user_email=request.POST['email'], lang=request.POST['lang'])

        return response

    def handle_sucessfull_register(self, user_email, lang):
        user = User.objects.get(email=user_email)
        user.is_active = True
        user.save()

        set_user_preference(user, LANGUAGE_KEY, lang)

        ForusProfile.create_for_user(user)


def message(request):
    message_text = request.GET.get('message')

    return render_to_response('edraak_forus/message.html', {
        'message': message_text
    })
