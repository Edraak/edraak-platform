# -*- coding: utf-8 -*-
"""
Tests for the Edraak i18n module.
"""

# The disable below because pylint is not recognizing request.META.
# pylint: disable=no-member

from django.test import TestCase, RequestFactory, override_settings
from django.conf import settings

from mock import patch
import ddt

from openedx.core.djangoapps.dark_lang.models import DarkLangConfig
from student.tests.factories import UserFactory

from edraak_i18n.middleware import DefaultLocaleMiddleware
from edraak_i18n.helpers import is_api_request


@ddt.ddt
class SettingsTest(TestCase):
    """
    Sanity checks for the settings related to the edraak_i18n module.
    """
    def test_if_enabled(self):
        """
        Ensures that the app is enabled.
        """
        self.assertIn('edraak_i18n', settings.INSTALLED_APPS, 'The app should be enabled by default in test.')

    def test_middleware_existing_but_disabled(self):
        """
        Ensures that the middleware is disabled by default.
        """
        self.assertNotIn('EDRAAK_I18N_LOCALE_MIDDLEWARE', settings.FEATURES, 'The middleware should be disabled.')
        self.assertIn('edraak_i18n.middleware.DefaultLocaleMiddleware', settings.MIDDLEWARE_CLASSES)

    @ddt.data(
        'openedx.core.djangoapps.lang_pref.middleware.LanguagePreferenceMiddleware',
        'openedx.core.djangoapps.dark_lang.middleware.DarkLangMiddleware',
        'django.middleware.locale.LocaleMiddleware',
    )
    def test_middleware_order(self, other_middleware):
        """
        Ensures that the middleware comes before any other locale-related middleware.
        """
        edraak_middleware = 'edraak_i18n.middleware.DefaultLocaleMiddleware'

        self.assertLess(
            a=settings.MIDDLEWARE_CLASSES.index(edraak_middleware),
            b=settings.MIDDLEWARE_CLASSES.index(other_middleware),
            msg='Edraak DefaultLocaleMiddleware should come before any other locale-related middleware'
        )


@ddt.ddt
class DefaultLocaleMiddlewareTest(TestCase):
    """
    Unit and integration tests for the DefaultLocaleMiddleware.
    """
    def setUp(self):
        """
        Set up the environment for the test case and ensures correct DarkLang configurations.
        """
        super(DefaultLocaleMiddlewareTest, self).setUp()

        self.middleware = DefaultLocaleMiddleware()
        self.request_factory = RequestFactory()

        self.user = UserFactory()

        DarkLangConfig(
            released_languages='en,ar,eo',
            changed_by=self.user,
            enabled=True
        ).save()

    @ddt.data('/dummy/', '/api/dummy')
    @patch.dict(settings.FEATURES, {'EDRAAK_I18N_LOCALE_MIDDLEWARE': False})
    @override_settings(LANGUAGE_CODE='eo')
    def test_deactivated(self, api_url):
        """
        Checks if the middleware behaves correctly when it is disabled using the feature flag.
        """
        req = self.request_factory.get(api_url)
        req.META['HTTP_ACCEPT_LANGUAGE'] = 'en'
        meta_before = req.META.copy()
        self.middleware.process_request(req)

        self.assertEquals(
            req.META['HTTP_ACCEPT_LANGUAGE'],
            'en',
            'The feature flag is disabled, the middleware should pass the request as is.'
        )

        self.assertDictEqual(
            d1=meta_before,
            d2=req.META,
            msg='The feature flag is disabled, the middleware should not change the request META.',
        )

    @patch.dict(settings.FEATURES, {'EDRAAK_I18N_LOCALE_MIDDLEWARE': True})
    @override_settings(LANGUAGE_CODE='eo')
    def test_activated_non_api(self):
        """
        Test the activated middleware on non-API pages.
        """
        req = self.request_factory.get('/dummy/')
        req.META['HTTP_ACCEPT_LANGUAGE'] = 'en'
        self.middleware.process_request(req)

        self.assertEquals(
            req.META['HTTP_ACCEPT_LANGUAGE'],
            'eo',
            'The feature flag is enabled, the middleware should change the language for non-API views.'
        )

        self.assertEquals(
            req.META['_HTTP_ACCEPT_LANGUAGE'],
            'en',
            'Should preserve the original language in another META variable.'
        )

    @ddt.data('/api/', '/user_api/')
    @patch.dict(settings.FEATURES, {'EDRAAK_I18N_LOCALE_MIDDLEWARE': True})
    @override_settings(LANGUAGE_CODE='ar')
    def test_enabled_api(self, api_url):
        """
        Ensures that the middleware doesn't change the non-API pages.
        """
        req = self.request_factory.get(api_url)
        client_language = 'en'
        req.META['HTTP_ACCEPT_LANGUAGE'] = client_language
        self.middleware.process_request(req)

        self.assertEquals(
            req.META['HTTP_ACCEPT_LANGUAGE'],
            client_language,
            'The feature flag is enabled, the middleware should NOT change the language for API views.'
        )

    @patch.dict(settings.FEATURES, {'EDRAAK_I18N_LOCALE_MIDDLEWARE': True})
    @override_settings(LANGUAGE_CODE='ar')
    def test_enabled_api_with_x_lang_header(self):
        """
        Ensure that `HTTP_X_API_ACCEPT_LANGUAGE` is used when applicable.
        """
        req = self.request_factory.get('/user_api/')
        client_language = 'en'
        req.META['HTTP_ACCEPT_LANGUAGE'] = 'fr-ca'
        req.META['HTTP_X_API_ACCEPT_LANGUAGE'] = client_language
        self.middleware.process_request(req)

        self.assertEquals(
            req.META['HTTP_ACCEPT_LANGUAGE'],
            client_language,
            'The feature flag is enabled, the middleware should NOT change the language for API views.'
        )

    @ddt.unpack
    @ddt.data(
        {'settings_lang': 'en', 'req_lang': 'en', 'valid': 'Skip to', 'invalid': u'Skïp tö'},
        {'settings_lang': 'en', 'req_lang': 'eo', 'valid': 'Skip to', 'invalid': u'Skïp tö'},
        {'settings_lang': 'eo', 'req_lang': 'en', 'valid': u'Skïp tö', 'invalid': 'Skip to'},
        {'settings_lang': 'eo', 'req_lang': 'eo', 'valid': u'Skïp tö', 'invalid': 'Skip to'},
    )
    @patch.dict(settings.FEATURES, {'EDRAAK_I18N_LOCALE_MIDDLEWARE': True})
    def test_enabled_middleware_in_request(self, settings_lang, req_lang, valid, invalid):
        """
        Testing different combinations of LANGUAGE_CODE and Accept-Language.

        The response language should always respect the `settings_lang` and ignores the `request_lang`.
        """
        with override_settings(LANGUAGE_CODE=settings_lang):
            headers = {
                'Accept-Language': req_lang,
            }

            res = self.client.get('/', **headers)
            self.assertContains(res, valid, msg_prefix='Incorrect language detected')
            self.assertNotContains(res, invalid, msg_prefix='Incorrect language detected')


@ddt.ddt
class HelpersTest(TestCase):
    """
    Test cases for the helper functions of edraak_i18n module.
    """
    def setUp(self):
        """
        Initializes the request factory.
        """
        super(HelpersTest, self).setUp()
        self.request_factory = RequestFactory()

    @ddt.unpack
    @ddt.data(
        {'path': '/api/', 'should_be_api': True},
        {'path': '/dashboard', 'should_be_api': False},
        {'path': '/', 'should_be_api': False},
        {'path': '/user_api/', 'should_be_api': True},
        {'path': '/notifier_api/', 'should_be_api': True}
    )
    def test_is_api_request_helper(self, path, should_be_api):
        """
        Tests the `is_api_request` helper on different params.
        """
        self.assertEquals(is_api_request(self.request_factory.get(path)), should_be_api)
