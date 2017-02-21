from mock import patch, Mock
import pytz
from datetime import datetime, timedelta
from urlparse import urlparse
import json
import ddt

from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory

from django.conf import settings
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from mako.filters import html_escape

from edraak_forus.models import ForusProfile
from edraak_forus.helpers import validate_forus_params

NEXT_WEEK = datetime.now(pytz.UTC) + timedelta(days=7)
PAST_WEEK = datetime.now(pytz.UTC) - timedelta(days=7)
NEXT_MONTH = datetime.now(pytz.UTC) + timedelta(days=30)
YESTERDAY = datetime.now(pytz.UTC) - timedelta(days=1)

TIME_FORMAT = '%Y-%m-%dT%H:%M:%S'


def build_forus_params(**kwargs):
    values = {
        'course_id': '',
        'email': '',
        'name': 'Abdulrahman (ForUs)',
        'enrollment_action': 'enroll',
        'country': 'JO',
        'level_of_education': 'hs',
        'gender': 'm',
        'year_of_birth': '1989',
        'lang': 'ar',
        'time': datetime.utcnow().strftime(TIME_FORMAT),
        'forus_hmac': 'dummy_hmac',
    }

    values.update(kwargs)

    return values


@patch('edraak_forus.helpers.calculate_hmac', Mock(return_value='dummy_hmac'))
class ForusAuthTest(ModuleStoreTestCase):
    """
    Test the ForUs auth.
    """

    def setUp(self):
        super(ForusAuthTest, self).setUp()
        self.course = CourseFactory.create(
            enrollment_start=PAST_WEEK,
            start=NEXT_WEEK,
        )

        self.user_email = 'forus.user@example.com'

        self.auth_url = reverse('forus_v1_auth')
        self.register_url = reverse('forus_v1_reg_api')
        self.course_root_url = '/courses/{}/info'.format(self.course.id)
        self.dashboard_url = reverse('dashboard')

    def _assertLoggedIn(self, msg_prefix=None):
        res_dashboard = self.client.get(self.dashboard_url)
        self.assertContains(res_dashboard, 'dashboard-main', msg_prefix=msg_prefix)

    def _assertLoggedOut(self):
        res_dashboard = self.client.get(self.dashboard_url)
        self.assertEquals(res_dashboard.status_code, 302, 'User is not logged out.')
        self._assertPathEquals(res_dashboard['Location'], '/login')

    def _assertPathEquals(self, url_a, url_b):
        path_a = urlparse(url_a).path
        path_b = urlparse(url_b).path
        self.assertEquals(path_a, path_b, 'Paths are not equal `{}` != `{}`'.format(path_a, path_b))

    @patch('openedx.core.djangoapps.user_api.views.set_logged_in_cookies')
    def test_open_enrolled_upcoming_course(self, mock_set_logged_in_cookies):
        # TODO: Split into more than one test case
        self.assertFalse(self.course.has_started())

        res_auth_1 = self.client.get(self.auth_url, self._build_forus_params())

        with self.assertRaises(User.DoesNotExist):
            user = User.objects.get(email=self.user_email)

        self.assertContains(res_auth_1, 'login-and-registration-container')

        self.client.post(self.register_url, self._build_forus_params(
            username='The Best ForUs User',
            password='random_password',
            honor_code=True,
        ))

        user = User.objects.get(email=self.user_email)
        self.assertTrue(ForusProfile.is_forus_user(user), 'This user is not a ForUs user.')

        self.assertTrue(mock_set_logged_in_cookies.called, 'Login cookies was not set!')
        self._assertLoggedIn(msg_prefix='The user is not logged in after clicking a course')

        self.client.logout()
        self.client.session.clear()

        self._assertLoggedOut()

        res_auth_2 = self.client.get(self.auth_url, self._build_forus_params())

        self.assertIsInstance(res_auth_2, HttpResponseRedirect)
        self.assertTrue(
            expr=res_auth_2['Location'].endswith(self.dashboard_url),
            msg='Auth does not redirect dashboard. It redirects to: `{}`'.format(res_auth_2['Location']),
        )

        self._assertLoggedIn(msg_prefix='The user is not logged in after clicking the form another time')

    def test_custom_registration_messages(self):
        res = self.client.get(self.auth_url, self._build_forus_params())
        self.assertNotContains(res, 'Create a new account')
        self.assertContains(res, 'Edraak account using ForUs')

        self.assertNotContains(res, 'Create your account')
        self.assertContains(res, 'Create your Edraak account')

        self.assertContains(res, 'toggle-form hidden')

    def _build_forus_params(self, **kwargs):
        params = build_forus_params(course_id=unicode(self.course.id), email=self.user_email, forus_hmac='dummy_hmac')
        params.update(**kwargs)
        return params


class ForUsMessagePageTest(TestCase):
    def setUp(self):
        super(ForUsMessagePageTest, self).setUp()

        self.url = reverse('forus_v1_message')

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
            start=NEXT_WEEK,
            enrollment_start=NEXT_WEEK,
            end=NEXT_WEEK,
            enrollment_end=NEXT_WEEK,
        )

        self.upcoming_course = CourseFactory.create(
            start=NEXT_WEEK,
            enrollment_start=YESTERDAY,
            end=NEXT_MONTH,
            enrollment_end=NEXT_WEEK,
        )

        self.current_course = CourseFactory.create(
            start=PAST_WEEK,
            enrollment_start=PAST_WEEK,
            end=NEXT_MONTH,
            enrollment_end=NEXT_WEEK,
        )

        self.closed_course = CourseFactory.create(
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
        with self.assertRaisesRegexp(ValidationError, 'Enrollment.*closed.*go.*ForUs') as cm:
            self._validate_params(course_id=unicode(self.closed_course.id))

        self._assertErrorCount(cm.exception, 1)

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
        with self.assertRaisesRegexp(ValidationError, '.*not.*opened.*go.*ForUs') as cm:
            self._validate_params(course_id=unicode(self.draft_course.id))

        self._assertErrorCount(cm.exception, 1)

    @ddt.data('', ' ', 'XZ')
    def test_invalid_country(self, bad_value):
        self._assertValidateData(
            field_id='country',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*country.*',
        )

    @ddt.data('', ' ')
    def test_invalid_name(self, bad_value):
        self._assertValidateData(
            field_id='name',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*name.*',
        )

    @ddt.data('', ' ', 'hello')
    def test_invalid_level_of_education(self, bad_value):
        self._assertValidateData(
            field_id='level_of_education',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*level of education.*',
        )

    @ddt.data('', ' ', 'o', 'hello')
    def test_invalid_gender(self, bad_value):
        self._assertValidateData(
            field_id='gender',
            bad_value=bad_value,
            exception_regexp='.*Invalid.*gender.*',
        )

    def _assertValidateData(self, field_id, bad_value, exception_regexp):
        with self.assertRaisesRegexp(ValidationError, exception_regexp) as cm:
            params = {field_id: bad_value}
            self._validate_params(course_id=unicode(self.upcoming_course.id), **params)

        self._assertErrorCount(cm.exception, 1)
        self.assertIn(field_id, cm.exception.message_dict)

    def _assertErrorCount(self, exception, expected_count):
        count = len(exception.messages)
        message = 'There should be one error instead of `{count}` in exception `{exception}`'.format(
            count=count,
            exception=exception,
        )
        self.assertEquals(count, expected_count, message)

    @patch('edraak_forus.helpers.calculate_hmac', Mock(return_value='dummy_hmac'))
    def _validate_params(self, **kwargs):
        params = build_forus_params(email=self.user_email)
        params.update(**kwargs)
        return validate_forus_params(params)


class RegistrationApiViewTest(ModuleStoreTestCase):
    wanted_hidden_fields = sorted([
        'course_id',
        'enrollment_action',
        'forus_hmac',
        'lang',
        'time',
        'country',
        'is_third_party_auth',
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
        self.url = reverse('forus_v1_reg_api')

    @patch.dict(settings.REGISTRATION_EXTRA_FIELDS, {'country': 'required'})
    def test_hidden_fields(self):
        res = self.client.get(self.url)

        form = json.loads(res.content)

        hidden_fields = sorted([
            str(field['name']) for field in form['fields']
            if field['type'] == 'hidden'
        ])

        self.assertListEqual(hidden_fields, self.wanted_hidden_fields)
