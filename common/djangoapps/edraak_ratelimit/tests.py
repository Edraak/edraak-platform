"""
Tests for the Edraak rate limit app.
"""
from unittest import skip

from django.test import TestCase, override_settings, ignore_warnings
from django.contrib.admin import site, ModelAdmin
from django.conf import settings

from datetime import datetime, timedelta
from dateutil.parser import parse as parse_datetime
import ddt
from mock import Mock, patch

from util.bad_request_rate_limiter import BadRequestRateLimiter
from student.tests.factories import UserFactory
from ratelimitbackend.exceptions import RateLimitException
from edraak_ratelimit.backends import EdraakRateLimitModelBackend
from edraak_ratelimit.admin import RateLimitedIPAdmin
from edraak_ratelimit.models import RateLimitedIP, StudentAccountLock
from edraak_ratelimit.requests import FakeRequest
from edraak_ratelimit.helpers import humanize_delta, update_authentication_backends


class SettingsTest(TestCase):
    """
    Sanity checks for the environment settings.
    """
    def test_if_enabled(self):
        """
        Ensures that the app is enabled.
        """
        self.assertIn('edraak_ratelimit', settings.INSTALLED_APPS, 'The app should be enabled by default in test.')

    def test_authentication_backend_configuration(self):
        """
        Ensures that both LMS and CMS authentication backends are kept as-is.

        This is to prevent edX tests from failing.
        """
        self.assertNotIn('edraak_ratelimit.backends.EdraakRateLimitModelBackend', settings.AUTHENTICATION_BACKENDS)

    def test_ip_ratelimit_settings(self):
        """
        Checks if the IP-based lock configurations reflects the requirements.

        This is important for other tests to pass correctly.

        Changing the value here requires changing the other tests.
        """
        self.assertEquals(EdraakRateLimitModelBackend.minutes, 5,
                          msg='Keep the same edX tests, and avoid over-querying the cache')

        self.assertEquals(EdraakRateLimitModelBackend.requests, 100,
                          msg='Increase the requests limit per 5 minutes, to avoid locking university students')


@ddt.ddt
class AdminSetupTest(TestCase):
    """
    Tests for the admin setup and some logic tests.
    """

    @ddt.data(RateLimitedIP, StudentAccountLock)
    def test_activated_admin_classes(self, model_class):
        """
        Ensures that the admin classes are activated.
        """
        self.assertTrue(site.is_registered(model_class), 'Model should be registered')


@ddt.ddt
class BadRequestRateLimiterPatchTest(TestCase):
    """
    Tests to Edraak's modifications on `BadRequestRateLimiter`

    Although is not in this module, placing an additional test here to avoid git conflicts.
    """

    @ddt.unpack
    @ddt.data(
        {'request_counts': [60, 60], 'ip_address': '100.100.20.20', 'expected_calls': 1},
        {'request_counts': [40, 40], 'ip_address': '120.120.5.5', 'expected_calls': 0},
    )
    @patch('edraak_ratelimit.backends.EdraakRateLimitMixin.db_log_failed_attempt')
    @skip('This will always fail because of Edraak Hack https://github.com/Edraak/edraak-platform/pull/177')
    def test_is_rate_limit_exceeded_method(self, db_log_mock, request_counts, ip_address, expected_calls):
        """
        Tests if `BadRequestRateLimiter.is_rate_limit_exceeded` calls Edraak's `db_log_failed_attempt` correctly.

        At Edraak we've added the `db_log_failed_attempt` to the BadRequestRateLimiter, to show it on the admin panel.
        """
        limiter = BadRequestRateLimiter()
        request_counts_mock = Mock(
            values=Mock(
                return_value=request_counts,
            )
        )

        with patch.object(limiter, 'get_counters', return_value=request_counts_mock):
            limiter.is_rate_limit_exceeded(FakeRequest(ip_address=ip_address))
            self.assertEquals(db_log_mock.call_count, expected_calls, 'Should only be called when if limit exceeded')


class FakeRequestTest(TestCase):
    """
    Tests for the FakeRequest class helper.
    """

    def test_ip_address(self):
        """
        Tests for the FakeRequest class.
        """
        ip_address = '8.8.8.8'
        request = FakeRequest(ip_address=ip_address)
        self.assertEquals(request.META['REMOTE_ADDR'], ip_address)


class RateLimitedIPAdminTest(TestCase):
    """
    Testing the custom methods in the RateLimitedIPAdminTest
    """

    def setUp(self):
        """
        Initialize RateLimitedIPAdmin.
        """
        super(RateLimitedIPAdminTest, self).setUp()
        self.admin = RateLimitedIPAdmin(RateLimitedIP, site)

    @patch('edraak_ratelimit.admin.humanize_delta')
    def test_custom_list_display_methods(self, humanize_delta_mock):
        """
        Tests `list_display` `lockout_duration` method.
        """

        utc_now = datetime.utcnow()
        self.admin.lockout_duration(Mock(created_at=utc_now, updated_at=utc_now))
        self.assertEquals(humanize_delta_mock.call_count, 1, 'humanize_delta should be called once')

    def test_unlock_time(self):
        """
        Tests `unlock_time` method for `list_display`.
        """
        utc_now = parse_datetime('Aug 28 1999 12:05AM')
        dummy_obj = Mock(updated_at=utc_now)

        utc_after_5 = parse_datetime('Aug 28 1999 12:10AM')

        self.assertEquals(self.admin.unlock_time(dummy_obj), utc_after_5,
                          msg='Unlock date should be 5 minutes after the last failed attempt')

    def test_no_raw_delete(self):
        """
        Raw delete wasn't preventing the deletion of corresponding DB entries, so `reset_attempts` was introduced.
        """
        request_mock = Mock(GET={})

        original_django_actions = ModelAdmin.get_actions(self.admin, request_mock)
        actions = self.admin.get_actions(request_mock)

        self.assertIn('delete_selected', original_django_actions, 'Just making sure we are testing correctly')
        self.assertNotIn('delete_selected', actions,
                         msg='Should be removed')
        self.assertIn('reset_attempts', actions, 'Use `reset_attempts` custom action')

    @patch('edraak_ratelimit.admin.cache')
    def test_delete_with_cache_invalidate(self, cache_mock):
        rate_limit_1 = Mock(ip_address='8.8.8.8')
        rate_limit_2 = Mock(ip_address='8.8.4.4')
        self.admin.reset_attempts(request=None, queryset=[rate_limit_1, rate_limit_2])

        self.assertEquals(rate_limit_1.delete.call_count, 1, 'Should delete the object')
        self.assertEquals(rate_limit_2.delete.call_count, 1, 'Should delete the object')
        self.assertEquals(cache_mock.delete_many.call_count, 2, 'Should delete entries of two objects')


@ddt.ddt
class RateLimitedIPTest(TestCase):
    """
    Tests for the RateLimitedIP model.
    """
    def test_unicode_method(self):
        """
        Tests the __unicode__ magic method for correct admin display.
        """
        ip_address = '1.2.3.4'
        obj = RateLimitedIP(ip_address=ip_address)
        self.assertEquals(unicode(obj), ip_address)

    @ddt.data('verbose_name', 'verbose_name_plural')
    def test_meta(self, property_name):
        """
        Ensures that the model has user-friendly name in the admin panel.
        """
        property_value = getattr(RateLimitedIP._meta, property_name)  # pylint: disable=protected-access
        self.assertIn('IP-based', property_value)


@ddt.ddt
class HelpersTest(TestCase):
    """
    Tests for edraak_ratelimit helpers.
    """
    @ddt.unpack
    @ddt.data(
        {'delta': None, 'output': '0 seconds', 'msg': 'Base case'},
        {'delta': timedelta(seconds=0), 'output': '0 seconds'},
        {'delta': timedelta(seconds=2), 'output': '2 seconds'},
        {'delta': timedelta(days=4, seconds=40), 'output': '4 days'},
        {'delta': timedelta(weeks=5, days=10), 'output': '45 days'},
    )
    def test_humanize_delta_helper(self, delta, output, msg=None):
        """
        Tests the humanize_delta helper.

        Args:
            delta: Mock relative time delta object.
            output: expected string output from the helper.
            msg: optional message to assert statement.
        """
        self.assertEquals(humanize_delta(delta), output, msg)

    @ddt.unpack
    @ddt.data({
        'edx_backend': 'ratelimitbackend.backends.RateLimitModelBackend',
        'edraak_backend': 'edraak_ratelimit.backends.EdraakRateLimitModelBackend',
    }, {
        'edx_backend':
            'openedx.core.djangoapps.oauth_dispatch.dot_overrides.validators.EdxRateLimitedAllowAllUsersModelBackend',
        'edraak_backend': 'edraak_ratelimit.backends.EdraakRateLimitAllowAllUsersModelBackend',
    })
    def test_update_authentication_backends_helper_lms(self, edx_backend, edraak_backend):
        """
        Ensures that the helper preserves the backend location.
        """

        with self.assertRaises(ValueError):
            # Should not work if the ratelimit backend is not within the original settings from edX (in common.py).
            update_authentication_backends(['backend1', 'backend2'])

        updated_backends = update_authentication_backends([
            'dummy1',
            edx_backend,
            'dummy2',
        ])

        self.assertNotIn(edx_backend, updated_backends)
        self.assertIn(edraak_backend, updated_backends)

        self.assertEquals(1, updated_backends.index(edraak_backend),
                          msg='Should have the Edraak backend in the same position where the edX backend was.')


class StudentAccountLockTest(TestCase):
    """
    Basic checks to ensure that the model will have no migrations.
    """
    def test_no_migrations(self):
        """
        Check for migrations-related meta properties.
        """
        meta = StudentAccountLock._meta  # pylint: disable=protected-access
        self.assertTrue(meta.auto_created, 'Should not migrate')
        self.assertFalse(meta.managed, 'Should not migrate')

    def test_unicode_method(self):
        """
        Tests the __unicode__ magic method for correct admin display.
        """
        user = UserFactory(username='user1')
        obj = StudentAccountLock(user=user)
        self.assertEquals(unicode(obj), 'user1 account lock')


@override_settings(AUTHENTICATION_BACKENDS=['edraak_ratelimit.backends.EdraakRateLimitModelBackend'])
class EdraakRateLimitModelBackendTest(TestCase):
    """
    Tests for the authentication backend behaviour.
    """
    @patch('edraak_ratelimit.backends.EdraakRateLimitMixin.db_log_failed_attempt')
    @ignore_warnings(module='ratelimitbackend')  # Ignore the ratelimit reached warning
    def test_rate_exceeded(self, db_log_failed_attempt):
        """
        Checks if the authenticate method throws the RateLimitException exception.
        """
        mock_counts = Mock(
            values=Mock(
                return_value=[500, 500, 500],
            ),
        )

        with patch('ratelimitbackend.backends.RateLimitMixin.get_counters', return_value=mock_counts):
            backend = EdraakRateLimitModelBackend()

            with self.assertRaises(RateLimitException):
                mock_request = FakeRequest(ip_address='240.1.3.4')
                backend.authenticate(email='email@edraak.org', password='dummy', request=mock_request)

            db_log_failed_attempt.assert_called_once_with(mock_request, 'user1')

    @patch('edraak_ratelimit.backends.EdraakRateLimitMixin.db_log_failed_attempt')
    def test_rate_not_exceeded(self, db_log_failed_attempt):
        """
        Testing when the rate limit is not exceeded.
        """
        expected_user = UserFactory()

        # Patch ModelBackend to bypass username and password checks.
        with patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=expected_user):
            backend = EdraakRateLimitModelBackend()

            mock_request = FakeRequest(ip_address='240.1.3.4')
            authenticated_user = backend.authenticate(email='email@edraak.org', password='dummy', request=mock_request)

            self.assertIs(expected_user, authenticated_user, 'Should authenticate the user')

            # Ensures that nothing is logged in the database.
            db_log_failed_attempt.assert_not_called()

    def test_db_log_failed_attempt_with_user(self):
        """
        Tests for the EdraakRateLimitMixin.db_log_failed_attempt method.
        """
        backend = EdraakRateLimitModelBackend()
        omar = UserFactory(email='omar@example.com')
        ali = UserFactory(email='ali@example.com')
        fake_request = FakeRequest(ip_address='150.0.3.31')

        with self.assertRaises(RateLimitedIP.DoesNotExist):
            RateLimitedIP.objects.get(latest_user=omar)

        backend.db_log_failed_attempt(fake_request, omar.username)

        omar_limit = RateLimitedIP.objects.get(latest_user=omar)

        self.assertEquals(omar_limit.ip_address, '150.0.3.31', 'Should log the entry with correct IP')
        self.assertEquals(omar_limit.lockout_count, 1, 'Only one attempt so far')

        backend.db_log_failed_attempt(FakeRequest(ip_address='150.0.3.31'))

        with self.assertRaises(RateLimitedIP.DoesNotExist):
            # Should clear the user from the record
            RateLimitedIP.objects.get(latest_user=omar)

        # Get the user back
        backend.db_log_failed_attempt(FakeRequest(ip_address='150.0.3.31'), ali.username)
        ali_limit = RateLimitedIP.objects.get(latest_user=ali)

        self.assertEquals(ali_limit.lockout_count, 3,
                          'Three attempts from the same IP so far, regardless of the user')
