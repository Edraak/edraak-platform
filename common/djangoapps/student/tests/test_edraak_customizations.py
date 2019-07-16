""" Test Edraak customizations """

import ddt

from django.conf import settings
from django.test import TestCase
from django.test.client import RequestFactory
from django.views.decorators.http import require_http_methods
from mock import patch
from student.edraak_helpers import is_origin_url_allowed, edraak_update_origin


@ddt.ddt
class TestEdraakHelpers(TestCase):

    @ddt.data(
        # If option is disabled, then it is always False
        (False, False, 'progs.edraak.com', False),
        (False, False, 'not_whitelisted_but_still_pattern.edraak.com', False),
        (False, False, 'totally.invalid.com', False),
        (False, True, 'progs.edraak.com', False),
        (False, True, 'not_whitelisted_but_still_pattern.edraak.com', False),
        (False, True, 'totally.invalid.com', False),

        (True, False, 'progs.edraak.com', True),  # whitelisted
        (True, False, 'not_whitelisted_but_still_pattern.edraak.com', True),  # pattern
        (True, False, 'totally.invalid.com', False),  # not a pattern and not whitelisted

        # True when all_allowed flag is set
        (True, True, 'progs.edraak.com', True),
        (True, True, 'not_whitelisted_but_still_pattern.edraak.com', True),
        (True, True, 'totally.invalid.com', True),
    )
    @ddt.unpack
    @patch.dict(
        settings.FEATURES, {
            'EDRAAK_AUTH_REDIRECT_ORIGINS_WHITELIST': ['progs.edraak.com', 'programs.edraak.com'],
            'EDRAAK_AUTH_REDIRECT_REGX_ORIGINS': [r'^(.*)(.edraak.com)$'],  # any subdomain of edraak.com
        }
    )
    def test_is_origin_url_allowed(self, option_enabled, all_allowed, origin, expected_result):
        with patch.dict(settings.FEATURES, EDRAAK_ENABLE_AUTH_EXTERNAL_REDIRECT=option_enabled):
            with patch.dict(settings.FEATURES, EDRAAK_AUTH_REDIRECT_ALLOW_ANY=all_allowed):
                self.assertEqual(is_origin_url_allowed(origin), expected_result)

    @patch('student.edraak_helpers.is_origin_url_allowed', return_value=False)
    def test_edraak_update_origin_must_not_update(self, mock):
        origin = 'progs.edraak.com'
        request = RequestFactory().get('/login?origin={}'.format(origin))
        context = {'data': {}}

        expected_context = {'data': {}}
        edraak_update_origin(request=request, context=context)

        self.assertDictEqual(context, expected_context)

    @patch('student.edraak_helpers.is_origin_url_allowed', return_value=True)
    def test_edraak_update_origin_must_update(self, mock):
        origin = 'progs.edraak.com'
        request = RequestFactory().get('/login?origin={}'.format(origin))
        context = {'data': {}}

        expected_context = {'data': {'origin': origin}}
        edraak_update_origin(request=request, context=context)

        self.assertDictEqual(context, expected_context)
