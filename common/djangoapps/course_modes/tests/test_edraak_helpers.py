"""
A test suite for Edraak's customization on the Courses Modes
"""
import unittest

import ddt
from django.conf import settings
from django.core.urlresolvers import reverse
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from mock import patch

from course_modes import edraak_helpers


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class HelpersTestCase(ModuleStoreTestCase):
    def test_default_settings(self):
        """
        Ensure that edX tests passes.
        """
        self.assertFalse(settings.FEATURES.get('EDRAAK_USE_MARKETING_COURSE_SUCCESS_PAGE'),
                         msg='The feature should be off by default, even during testing.')

    def test_feature_by_default_helper(self):
        """
        Also test the URL helper.
        """
        self.assertFalse(edraak_helpers.is_marketing_course_success_page_enabled(), 'Should be disabled by default')
        self.assertEqual(edraak_helpers.get_course_success_page_url('a/b/c'), reverse('dashboard'))

    @ddt.unpack
    @ddt.data(
        {
            # Reason: Marketing site is disabled
            'mktg_urls': {'ROOT': 'https://omar', 'COURSE_SUCCESS_PAGE_FORMAT': '/course/{course_id}/success'},
            'features': {'ENABLE_MKTG_SITE': False},
            'error_regexp': '.*MARKETING.*ENABLE_MKTG_SITE.*',
        },
        {
            # Reason: Missing course details api format configuration
            'mktg_urls': {'ROOT': 'https://omar'},
            'features': {'ENABLE_MKTG_SITE': True},
            'error_regexp': '.*MARKETING.*COURSE_SUCCESS_PAGE_FORMAT.*',
        },
        {
            # Reason: Missing MKTG_URL['ROOT']
            'mktg_urls': {'COURSE_SUCCESS_PAGE_FORMAT': '/api/{course_id}/'},
            'features': {'ENABLE_MKTG_SITE': True},
            'error_regexp': '.*MARKETING.*ROOT.*',
        },
        {
            # Reason: Missing `course_id` in the API.
            'mktg_urls': {'ROOT': 'https://omar', 'COURSE_SUCCESS_PAGE_FORMAT': '/api/{course_key}/'},
            'features': {'ENABLE_MKTG_SITE': True},
            'error_regexp': '.*MARKETING.*course_id.*',
        },
    )
    @patch.dict(settings.FEATURES, EDRAAK_USE_MARKETING_COURSE_SUCCESS_PAGE=True)
    def test_enabled_feature_but_invalid_configs(self, mktg_urls, features, error_regexp):
        with patch.dict(settings.FEATURES, features):
            with patch.object(settings, 'MKTG_URLS', mktg_urls):
                with self.assertRaisesRegexp(Exception, error_regexp):
                    edraak_helpers.is_marketing_course_success_page_enabled()

    @patch.dict(settings.FEATURES, ENABLE_MKTG_SITE=True, EDRAAK_USE_MARKETING_COURSE_SUCCESS_PAGE=True)
    @patch.object(settings, 'MKTG_URLS', {
        'ROOT': 'https://mktg.com',
        'COURSE_SUCCESS_PAGE_FORMAT': '/course/{course_id}/success',
    })
    def test_enabled_feature_and_marketing(self):
        """
        Also test the URL helper.
        """
        self.assertTrue(edraak_helpers.is_marketing_course_success_page_enabled(), 'Should be enabled')
        self.assertEqual(edraak_helpers.get_course_success_page_url('a/b/c'), 'https://mktg.com/course/a/b/c/success')

    def _test_get_progs_url(self, path):
        with patch('course_modes.edraak_helpers.get_language', return_value='en'):
            self.assertEqual(edraak_helpers.get_progs_url(path), 'https://progs.com/en/page_path')

        with patch('course_modes.edraak_helpers.get_language', return_value='ar'):
            self.assertEqual(edraak_helpers.get_progs_url(path), 'https://progs.com/page_path')

    @ddt.data('/page_path', 'page_path')
    def test_get_progs_url(self, path):
        with patch.object(settings, 'PROGS_URLS', {'ROOT': 'https://progs.com/'}):
            self._test_get_progs_url(path)

        with patch.object(settings, 'PROGS_URLS', {'ROOT': 'https://progs.com'}):
            self._test_get_progs_url(path)
