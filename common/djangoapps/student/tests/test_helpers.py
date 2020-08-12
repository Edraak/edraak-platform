""" Test Student helpers """

import logging

import ddt
from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from django.test.utils import override_settings
from mock import patch
from testfixtures import LogCapture

from student.helpers import get_next_url_for_login_page
from openedx.core.djangoapps.site_configuration.tests.test_util import with_site_configuration_context

LOGGER_NAME = "student.helpers"


@ddt.ddt
class TestLoginHelper(TestCase):
    """Test login helper methods."""
    static_url = settings.STATIC_URL

    def setUp(self):
        super(TestLoginHelper, self).setUp()
        self.request = RequestFactory()

    @staticmethod
    def _add_session(request):
        """Annotate the request object with a session"""
        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session.save()

    @ddt.data(
        (logging.WARNING, "WARNING", "https://www.amazon.com", "text/html", None,
         "Unsafe redirect parameter detected after login page: u'https://www.amazon.com'"),
        (logging.WARNING, "WARNING", "testserver/edx.org/images/logo", "text/html", None,
         "Redirect to theme content detected after login page: u'testserver/edx.org/images/logo'"),
        (logging.INFO, "INFO", "favicon.ico", "image/*", "test/agent",
         "Redirect to non html content 'image/*' detected from 'test/agent' after login page: u'favicon.ico'"),
        (logging.WARNING, "WARNING", "https://www.test.com/test.jpg", "image/*", None,
         "Unsafe redirect parameter detected after login page: u'https://www.test.com/test.jpg'"),
        (logging.INFO, "INFO", static_url + "dummy.png", "image/*", "test/agent",
         "Redirect to non html content 'image/*' detected from 'test/agent' after login page: u'" + static_url +
         "dummy.png" + "'"),
        (logging.WARNING, "WARNING", "test.png", "text/html", None,
         "Redirect to url path with specified filed type 'image/png' not allowed: u'test.png'"),
        (logging.WARNING, "WARNING", static_url + "dummy.png", "text/html", None,
         "Redirect to url path with specified filed type 'image/png' not allowed: u'" + static_url + "dummy.png" + "'"),
    )
    @ddt.unpack
    def test_next_failures(self, log_level, log_name, unsafe_url, http_accept, user_agent, expected_log):
        """ Test unsafe next parameter """
        with LogCapture(LOGGER_NAME, level=log_level) as logger:
            req = self.request.get(reverse("login") + "?next={url}".format(url=unsafe_url))
            req.META["HTTP_ACCEPT"] = http_accept  # pylint: disable=no-member
            req.META["HTTP_USER_AGENT"] = user_agent  # pylint: disable=no-member
            get_next_url_for_login_page(req)
            logger.check(
                (LOGGER_NAME, log_name, expected_log)
            )

    @ddt.data(
        ('/dashboard', 'testserver'),
        ('https://edx.org/courses', 'edx.org'),
        ('https://test.edx.org/courses', 'edx.org'),
        ('https://test2.edx.org/courses', 'edx.org'),
    )
    @ddt.unpack
    @override_settings(LOGIN_REDIRECT_WHITELIST=['test.edx.org', 'test2.edx.org'])
    def test_safe_next(self, next_url, host):
        """ Test safe next parameter """
        req = self.request.get(reverse("login") + "?next={url}".format(url=next_url), HTTP_HOST=host)
        req.META["HTTP_ACCEPT"] = "text/html"  # pylint: disable=no-member
        next_page = get_next_url_for_login_page(req)
        self.assertEqual(next_page, next_url)

    @patch('student.helpers.third_party_auth.pipeline.get')
    @ddt.data(
        # Test requests outside the TPA pipeline - tpa_hint should be added.
        (None, '/dashboard', '/dashboard', False),
        ('', '/dashboard', '/dashboard', False),
        ('', '/dashboard?tpa_hint=oa2-google-oauth2', '/dashboard?tpa_hint=oa2-google-oauth2', False),
        ('saml-idp', '/dashboard', '/dashboard?tpa_hint=saml-idp', False),
        # THIRD_PARTY_AUTH_HINT can be overridden via the query string
        ('saml-idp', '/dashboard?tpa_hint=oa2-google-oauth2', '/dashboard?tpa_hint=oa2-google-oauth2', False),

        # Test requests inside the TPA pipeline - tpa_hint should not be added, preventing infinite loop.
        (None, '/dashboard', '/dashboard', True),
        ('', '/dashboard', '/dashboard', True),
        ('', '/dashboard?tpa_hint=oa2-google-oauth2', '/dashboard?tpa_hint=oa2-google-oauth2', True),
        ('saml-idp', '/dashboard', '/dashboard', True),
        # OK to leave tpa_hint overrides in place.
        ('saml-idp', '/dashboard?tpa_hint=oa2-google-oauth2', '/dashboard?tpa_hint=oa2-google-oauth2', True),
    )
    @ddt.unpack
    def test_third_party_auth_hint(self, tpa_hint, next_url, expected_url, running_pipeline, mock_running_pipeline):
        mock_running_pipeline.return_value = running_pipeline

        def validate_login():
            req = self.request.get(reverse("login") + "?next={url}".format(url=next_url))
            req.META["HTTP_ACCEPT"] = "text/html"  # pylint: disable=no-member
            self._add_session(req)
            next_page = get_next_url_for_login_page(req)
            self.assertEqual(next_page, expected_url)

        with override_settings(FEATURES=dict(settings.FEATURES, THIRD_PARTY_AUTH_HINT=tpa_hint)):
            validate_login()

        with with_site_configuration_context(configuration=dict(THIRD_PARTY_AUTH_HINT=tpa_hint)):
            validate_login()
