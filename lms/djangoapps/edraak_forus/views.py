"""
The views in this module mimics the `student.views` registration form and API.
This is useful to enable so much code reuse.
"""

import logging
import json
from urllib import urlencode
from util.json_request import JsonResponse
from third_party_auth import pipeline

from django.conf import settings
from django.core.urlresolvers import reverse
from django.shortcuts import redirect
from django.contrib.auth import logout, login
from django.contrib.auth.models import User
from django.utils.translation import ugettext as _
from django.core.exceptions import ValidationError
from django.views.generic import View, TemplateView
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils.decorators import method_decorator

from edxmako.shortcuts import render_to_response
from enrollment.errors import CourseEnrollmentExistsError
from enrollment.api import add_enrollment
from lang_pref import LANGUAGE_KEY
from opaque_keys.edx.keys import CourseKey
from opaque_keys import InvalidKeyError
from openedx.core.djangoapps.user_api.views import RegistrationView
from openedx.core.djangoapps.user_api.preferences.api import set_user_preference
from student_account.views import _local_server_get
from student.cookies import delete_logged_in_cookies
from student.helpers import get_next_url_for_login_page
from xmodule.modulestore.django import modulestore
from edraak_forus.models import ForusProfile
from edraak_forus.helpers import ForusValidator, forus_error_redirect, ForusRegistrationFields

log = logging.getLogger(__name__)


class AuthView(View):
    """
    Authentication View class
    """
    def get(self, request):
        """
        Manage GET requests
        """
        try:
            forus_params = ForusValidator(request.GET).validate()
        except ValidationError as error:
            return forus_error_redirect(*error.messages)

        course_string_id = forus_params['course_id']
        course_key = CourseKey.from_string(unicode(course_string_id))

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

            return self.enroll(user, course_string_id, course_key)
        except User.DoesNotExist:
            return self.render_auth_form(request, forus_params)

    def enroll(self, user, course_id, course_key):
        """
        Enroll users
        """
        try:
            try:
                add_enrollment(user.username, course_id)
            except CourseEnrollmentExistsError:
                pass

            course = modulestore().get_course(course_key)

            if course.has_started():
                return redirect('course_root', unicode(course_key))
            else:
                return redirect('dashboard')
        except InvalidKeyError:
            return forus_error_redirect(_("Invalid course id"))
        except Exception as error:  # pylint: disable=broad-except, invalid-name
            log.exception(error)
            return forus_error_redirect(_("Could not enroll"))

    def get_registration_form_description(self, request, forus_params):
        """Retrieve form descriptions from the user API.

        Arguments:
            request (HttpRequest): The original request, used to retrieve session info.
            forus_params (dict): forus params values.

        Returns:
            JSON-serialized registration form descriptions.
        """
        form = json.loads(_local_server_get(reverse('forus_v1:reg_api'), request.session))

        for field in form['fields']:
            field_name = field['name']

            if field_name in ForusRegistrationFields.get_populated_fields():
                field['defaultValue'] = forus_params[field_name]

            if 'username' == field_name:
                field['defaultValue'] = forus_params['name'].strip()

        return form

    def render_auth_form(self, request, forus_params):
        """
        Render the combined login/registration form, defaulting to login

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


class RegistrationApiView(RegistrationView):
    """
    Registration API view
    """
    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        response = super(RegistrationApiView, self).get(request)
        registration_form = json.loads(response.content)

        for field_name in ForusRegistrationFields.get_forus_fields():
            registration_form['fields'].append({
                'name': field_name,

                # Make it ran
                'required': True,
                'errorMessages': {},
                'restrictions': {},
                'form': 'register',
                'placeholder': '',
            })

        registration_form['submit_url'] = reverse('forus_v1:reg_api')

        for field in registration_form['fields']:
            field_name = field['name']

            if field_name in ForusRegistrationFields.get_hidden_fields():
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
        """
        Handle post requests
        """
        try:
            ForusValidator(request.POST).validate()
        except ValidationError as error:
            return forus_error_redirect(*error.messages)

        response = super(RegistrationApiView, self).post(request)

        if 200 == response.status_code:
            self.handle_sucessfull_register(user_email=request.POST['email'], lang=request.POST['lang'])

        return response

    def handle_sucessfull_register(self, user_email, lang):
        """
        Save user and set to active upon successful registration
        """
        user = User.objects.get(email=user_email)
        user.is_active = True
        user.save()

        set_user_preference(user, LANGUAGE_KEY, lang)

        ForusProfile.create_for_user(user)


class MessageView(TemplateView):
    """
    View to display error and information messages to the ForUs users.
    """
    template_name = 'edraak_forus/message.html'

    def get_context_data(self, **kwargs):
        """
        Render message template with context message
        """
        context = super(MessageView, self).get_context_data(**kwargs)
        context['message'] = self.request.GET.get('message')
        return context
