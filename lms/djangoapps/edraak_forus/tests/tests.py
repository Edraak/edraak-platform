"""
Edraak ForUs Tests
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.utils.http import urlencode
from freezegun import freeze_time

import json
from datetime import datetime, timedelta
import ddt
import pytz
from mako.filters import html_escape
from mock import patch, Mock

from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory

from edraak_forus.helpers import ForusValidator, calculate_hmac, stringify_forus_params_to_msg_to_hash
from edraak_forus.models import ForusProfile
from edraak_forus.tests.helpers import build_forus_params

PAST_WEEK = datetime.now(pytz.UTC) - timedelta(days=7)
NEXT_MONTH = datetime.now(pytz.UTC) + timedelta(days=30)
NEXT_WEEK = datetime.now(pytz.UTC) + timedelta(days=7)
YESTERDAY = datetime.now(pytz.UTC) - timedelta(days=1)


class SettingsTest(TestCase):
    """
    Sanity checks for the environment settings
    """
    def test_if_enabled(self):
        """
        Ensure the app is enabled
        """
        self.assertIn('edraak_forus', settings.INSTALLED_APPS, 'Forus app should be enabled in tests')

    def test_url_in_settings(self):
        self.assertEqual(settings.FORUS_BASE_URL, 'http://forus.jo')

    def test_secret_key_in_settings(self):
        self.assertEqual(settings.FORUS_AUTH_SECRET_KEY, 'dummy_auth_secret_key')


@patch('edraak_forus.helpers.calculate_hmac', Mock(return_value='dummy_hmac'))
class ForusAuthViewTest(ModuleStoreTestCase):
    """
    Test the ForUs auth.
    """

    def setUp(self):
        super(ForusAuthViewTest, self).setUp()
        self.course = CourseFactory.create(
            enrollment_start=PAST_WEEK,
            start=NEXT_WEEK,
        )

        self.user_email = 'forus.user@example.com'

        self.auth_url = reverse('forus_v1:auth')
        self.register_url = reverse('forus_v1:reg_api')
        # Omar note: This shouldn't be done manually, it should be built using `reverse()`
        self.course_root_url = '/courses/{}/info'.format(self.course.id)
        self.dashboard_url = reverse('dashboard')

    def assert_logged_in(self, msg_prefix=None):
        """
        Test if user is logged in
        """
        res_dashboard = self.client.get(self.dashboard_url)
        # testing dashboard url to see if user is logged in
        self.assertContains(res_dashboard, 'dashboard-main', msg_prefix=msg_prefix)

    def assert_logged_out(self):
        """
        Test if user is logged out
        """
        res_dashboard = self.client.get(self.dashboard_url)

        self.assertRedirects(
            res_dashboard,
            '/login?next=/dashboard',
            msg_prefix='User is not logged out.')

    def test_course_not_started(self):
        self.assertFalse(self.course.has_started())

    def test_user_not_registered(self):
        res = self.client.get(self.auth_url, self._build_forus_params())

        with self.assertRaises(User.DoesNotExist):
            User.objects.get(email=self.user_email)

        self.assertContains(res, 'login-and-registration-container')

    def test_user_created(self):
        res = self.client.post(self.register_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
        ))

        self.assertContains(res, 'success', msg_prefix='The user should be registered')

    def test_user_is_forus_user(self):
        self.client.post(self.register_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
        ))

        user = User.objects.get(email=self.user_email)
        self.assertTrue(ForusProfile.is_forus_user(user), 'This user is not a ForUs user.')

    def test_course_enrollment(self):
        # Create a course that is started and open for enrollment
        course_started = datetime.now(pytz.UTC) - timedelta(days=2)
        course = CourseFactory.create(
            enrollment_start=PAST_WEEK,
            start=course_started,
        )

        # Register a ForUs user
        # Omar note: It should be registered and enrolled in the course, no?
        self.client.post(self.register_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
            course_id=unicode(course.id),
        ))

        # Logout
        self.client.logout()
        self.client.session.clear()

        # Simulate a returning ForUs user clicking on a course from ForUs
        res = self.client.get(self.auth_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
            course_id=unicode(course.id),
        ))

        course_root_url = reverse('course_root', kwargs={'course_id': course.id})

        # Checks if the redirect is correctly configured when the marketing site is enabled
        self.assertRedirects(res, course_root_url)

        # Logout, again
        self.client.logout()
        self.client.session.clear()

        # Simulate a returning ForUs user clicking on a course from ForUs, again.
        res = self.client.get(self.auth_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
            course_id=unicode(course.id),
        ))

        self.assertRedirects(res, course_root_url)

    def test_invalid_course_id(self):
        # Omar note: I think this step is not necessary.
        self.client.post(self.register_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
        ))

        self.client.logout()
        self.client.session.clear()

        res = self.client.get(self.auth_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
            course_id='invalid_course_id'
        ))

        querystring = {
            'message': 'Invalid course id has been provided.'
        }

        # Omar note: This check is fragile and will break on any changes.
        # I think it's better to check a portion of the message in the actual response, instead of checking for the
        # exact URL.
        print res
        self.assertRedirects(res, '{}?{}'.format(reverse('forus_v1:message'), urlencode(querystring)))

    @patch('openedx.core.djangoapps.user_api.views.set_logged_in_cookies')
    def test_open_enrolled_upcoming_course(self, mock_set_logged_in_cookies):
        """
        Testing the behaviour of the redirect for upcoming courses.
        """
        self.client.post(self.register_url, self._build_forus_params(
            username='The_Best_ForUs_User',
            password='random_password',
            honor_code=True,
        ))
        self.assertTrue(mock_set_logged_in_cookies.called, 'Login cookies was not set!')
        self.assert_logged_in(msg_prefix='The user is not logged in after clicking a course')

        self.client.logout()
        self.client.session.clear()
        self.assert_logged_out()

        res = self.client.get(self.auth_url, self._build_forus_params())
        self.assert_logged_in(msg_prefix='The user is not logged in after clicking the form another time')

        # It should go to dashboard.
        self.assertRedirects(res, self.dashboard_url)

    def test_custom_registration_messages(self):
        res = self.client.get(self.auth_url, self._build_forus_params())
        self.assertNotContains(res, 'Create a new account')
        self.assertContains(res, 'Edraak account using ForUs')

        self.assertNotContains(res, 'Create your account')
        self.assertContains(res, 'Create your Edraak account')

        self.assertContains(res, 'toggle-form hidden')

    def _build_forus_params(self, **kwargs):
        """
        Build forus params with updated values according to test
        """
        params = build_forus_params(course_id=unicode(self.course.id), email=self.user_email, forus_hmac='dummy_hmac')
        params.update(**kwargs)
        return params


class ForUsMessagePageTest(TestCase):
    """
    Test message page
    """
    def setUp(self):
        super(ForUsMessagePageTest, self).setUp()

        self.url = reverse('forus_v1:message')

    def test_message_page_with_no_error(self):
        """
        We don't want to the word "error" to appear in the message page.
        """

        message = 'The course was not found.'

        res = self.client.get(self.url, {
            'message': message,
        })

        self.assertContains(res, message, msg_prefix='The message is missing from the page')
        self.assertNotContains(res, 'error', msg_prefix='The page contains the work `error` which is confusing')

    def test_no_xss(self):
        message = '<script>alert("Hello")</script>'
        escaped_message = html_escape(message)

        self.assertNotEqual(message, escaped_message, 'Something is wrong, message is not being escaped!')
        self.assertNotIn('<script>', escaped_message, 'Something is wrong, message is not being escaped!')

        res = self.client.get(self.url, {
            'message': message,
        })

        self.assertNotContains(res, message, msg_prefix='The page is XSS vulnerable')
        self.assertContains(res, escaped_message, msg_prefix='The page encodes the message incorrectly')


@ddt.ddt
class ParamValidatorTest(ModuleStoreTestCase):
    """
    Tests for the params validator functions.
    """

    user_email = 'forus.user.faramvalidatortest@example.com'

    def setUp(self):
        super(ParamValidatorTest, self).setUp()

        self.draft_course = CourseFactory.create(
            org='org.41',
            display_name='Run_41',
            number='course_41',
            start=NEXT_WEEK,
            enrollment_start=NEXT_WEEK,
            end=NEXT_WEEK,
            enrollment_end=NEXT_WEEK,
        )

        self.upcoming_course = CourseFactory.create(
            org='org.51',
            display_name='Run_51',
            number='course_51',
            start=NEXT_WEEK,
            enrollment_start=YESTERDAY,
            end=NEXT_MONTH,
            enrollment_end=NEXT_WEEK,
        )

        self.current_course = CourseFactory.create(
            org='org.61',
            display_name='Run_61',
            number='course_61',
            start=PAST_WEEK,
            enrollment_start=PAST_WEEK,
            end=NEXT_MONTH,
            enrollment_end=NEXT_WEEK,
        )

        self.closed_course = CourseFactory.create(
            org='org.71',
            display_name='Run_71',
            number='course_71',
            start=PAST_WEEK,
            enrollment_start=PAST_WEEK,
            end=YESTERDAY,
            enrollment_end=YESTERDAY,
        )

    def test_sanity_check(self):
        """
        The user shouldn't exist, so the whole test case succeeds.
        """
        with self.assertRaises(User.DoesNotExist):
            User.objects.get(email=self.user_email)

    def test_closed_course(self):
        """
        Test if course is closed
        """
        with self.assertRaisesRegexp(ValidationError, 'Enrollment.*closed.*go.*ForUs') as course_module:
            self._validate_params(course_id=unicode(self.closed_course.id))

        self.assert_error_count(course_module.exception, 1)

    def test_current_course(self):
        try:
            self._validate_params(course_id=unicode(self.current_course.id))
        except ValidationError as exc:
            self.fail('The course is open and everything is fine, yet there is an error: `{}`'.format(exc))

    def test_upcoming_course(self):
        try:
            self._validate_params(course_id=unicode(self.upcoming_course.id))
        except ValidationError as exc:
            self.fail('The course is upcoming and everything is fine, yet there is an error: `{}`'.format(exc))

    def test_draft_course(self):
        with self.assertRaisesRegexp(ValidationError, '.*not.*opened.*go.*ForUs') as course_module:
            self._validate_params(course_id=unicode(self.draft_course.id))

        self.assert_error_count(course_module.exception, 1)

    @ddt.data('', ' ', 'XZ')
    def test_invalid_country(self, bad_value):
        self.assert_validated_data(
            field_id='country',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*country.*',
        )

    @ddt.data('', ' ')
    def test_invalid_name(self, bad_value):
        self.assert_validated_data(
            field_id='name',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*name.*',
        )

    @ddt.data('', ' ', 'hello')
    def test_invalid_level_of_education(self, bad_value):
        self.assert_validated_data(
            field_id='level_of_education',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*level of education.*',
        )

    @ddt.data('', ' ', 'x', 'hello')
    def test_invalid_gender(self, bad_value):
        self.assert_validated_data(
            field_id='gender',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*gender.*',
        )

    def test_invalid_hmac(self):
        self.assert_validated_data(
            field_id='forus_hmac',
            bad_value='wrong_dummy_hmac',
            exception_regexp='The security check has failed on the provided parameters'
        )

    def test_missing_hmac(self):
        params = build_forus_params(email=self.user_email, course_id=unicode(self.upcoming_course.id))
        params.pop('forus_hmac', None)
        with self.assertRaisesRegexp(ValidationError, 'The security check has failed on the provided parameters') \
                as error:
            ForusValidator(params).validate()

        self.assertIn('forus_hmac', error.exception.message_dict)

    @freeze_time('2017-01-14 03:21:34')
    def test_calculate_hmac(self):
        # pylint: disable=line-too-long
        """
        This tests the calculate hmac helper in ForUs,
        The time is forzen to '2017-01-14 03:21:34'
        Course_id is frozen to org.51/course_51/Run_51

        Use bash tool to generate expected hmac:
            1. store msg to be hashed: ```export msg="course_id=org.51/course_51/Run_51;email=forus.user.faramvalidatortest@example.com;name=Abdulrahman (ForUs);enrollment_action=enroll;country=JO;level_of_education=hs;gender=m;year_of_birth=1989;lang=en;time=2017-01-14T03:21:34"```
            2. hash msg: ```echo -n "$msg" | openssl dgst -sha256 -hmac "dummy_auth_secret_key"```

        Compare with calculate hmac and assert Equals return value.
        """

        params = build_forus_params(email=self.user_email, course_id=unicode(self.upcoming_course.id))
        msg_to_hash = stringify_forus_params_to_msg_to_hash(params)

        expected_hmac = '2991d512adb3bd289ca42ff5125332c9f4e528fb0ad2447b62f014f0d98b6f8c'
        actual_hmac = calculate_hmac(msg_to_hash)

        self.assertEquals(actual_hmac, expected_hmac)

    def assert_validated_data(self, field_id, bad_value, exception_regexp):
        """
        A test helper for testing the the validator exceptions.
        """
        with self.assertRaisesRegexp(ValidationError, exception_regexp) as course_module:
            params = {field_id: bad_value}
            self._validate_params(course_id=unicode(self.upcoming_course.id), **params)

        self.assert_error_count(course_module.exception, 1)
        self.assertIn(field_id, course_module.exception.message_dict)

    def assert_error_count(self, exception, expected_count):
        """
        A test helper to ensure correct error count with helpful message.
        """
        count = len(exception.messages)
        message = 'There should be one error instead of `{count}` in exception `{exception}`'.format(
            count=count,
            exception=exception,
        )
        self.assertEquals(count, expected_count, message)

    @patch('edraak_forus.helpers.calculate_hmac', Mock(return_value='dummy_hmac'))
    def _validate_params(self, **kwargs):
        """
        Validate params with ForusValidator.
        """
        params = build_forus_params(email=self.user_email)
        params.update(**kwargs)
        return ForusValidator(params).validate()


class RegistrationApiViewTest(ModuleStoreTestCase):
    """
    Test class for the registration API view
    """
    wanted_hidden_fields = sorted([
        'course_id',
        'enrollment_action',
        'forus_hmac',
        'lang',
        'time',
        'country',
        'email',
        'gender',
        'level_of_education',
        'name',
        'year_of_birth',
        'password',
        'goals',
    ])

    def setUp(self):
        super(RegistrationApiViewTest, self).setUp()
        self.url = reverse('forus_v1:reg_api')

    def test_hidden_fields(self):
        res = self.client.get(self.url)

        form = json.loads(res.content)

        hidden_fields = sorted([
            str(field['name']) for field in form['fields']
            if field['type'] == 'hidden'
        ])
        self.assertListEqual(hidden_fields, self.wanted_hidden_fields)
