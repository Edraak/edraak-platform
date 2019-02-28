"""
Tests for the Arabic MathJax extension setup.
"""
from django.conf import settings
from edxmako.shortcuts import render_to_string
from mock import patch
import requests

from edraak_tests.tests.helpers import ModuleStoreLoggedInTestCase


class ArabicMathJaxExtensionTest(ModuleStoreLoggedInTestCase):
    """
    Sanity checks for the MathJax Arabic extension.
    """

    BASE_URL = 'https://cdn.rawgit.com/Edraak/arabic-mathjax/v1.1/dist'
    FILE_NAME = 'arabic.js'
    FILE_NAME_WITH_PACKAGE = '[arabic]/arabic.js'
    MATHJAX_FILE = 'MathJax.js'

    def test_feature_disabled_by_default(self):
        self.assertFalse(settings.FEATURES.get('ENABLE_ARABIC_MATHJAX'), 'The feature should be disabled by default')

    def render_mathjax_include(self):
        """
        Helper to the MathJax include partial html.
        """
        return render_to_string('mathjax_include.html', {})

    def test_sanity_check(self):
        html = self.render_mathjax_include()
        self.assertIn(self.MATHJAX_FILE, html)  # A courseware page should include the MathJax

        # A courseware page should NOT include the Arabic extension when the feature is disabled
        self.assertNotIn(self.FILE_NAME_WITH_PACKAGE, html)

    @patch.dict(settings.FEATURES, ENABLE_ARABIC_MATHJAX=True)
    def test_feature_enabled(self):
        html = self.render_mathjax_include()

        # A courseware page should include the Arabic.js extension when the feature is enabled
        self.assertIn(self.FILE_NAME_WITH_PACKAGE, html)

        # Did you update the version? Update it here as well to ensure the `test_cdn_content` works fine'
        self.assertIn(self.BASE_URL, html)

    def test_cdn_content(self):
        """
        Make sure the CDN works.
        """
        res = requests.get('{base}/{file}'.format(
            base=self.BASE_URL,
            file=self.FILE_NAME,
        ))

        self.assertEquals(res.status_code, 200, 'The extension file must be reachable.')
        self.assertIn('Arabic TeX Startup', res.text, msg='The extension file must contain the correct content.')
