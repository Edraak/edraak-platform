import ddt
from django.conf import settings
from django.core.urlresolvers import reverse
from django.test import TestCase
from edxmako import lookup_template
from mock import patch
from unittest import skipUnless

from courseware.testutils import RenderXBlockTestMixin
from util.url import reload_django_url_config
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from edraak_tests.tests.helpers import ModuleStoreTestCaseLoggedIn


@ddt.ddt
@skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class ViewportMetaTestCase(TestCase):
    """
    Tests the Edraak's viewport configs.
    """
    def test_defaults(self):
        """
        Testing the default settings for the feature flags.
        """
        self.assertTrue(settings.FEATURES['EDRAAK_VIEWPORT_CHANGES'])

    def test_edraak_desktop_viewport_config(self):
        """
        Use Edraak's QA recommendation by removing the viewport form `main.html`.
        """
        res = self.client.get('/login')
        self.assertNotContains(res, 'name="viewport"')

    @patch.dict(settings.FEATURES, EDRAAK_VIEWPORT_CHANGES=False)
    def test_edx_desktop_viewport_config(self):
        """
        Disable the Edraak customization and revert to edX's default.
        """
        res = self.client.get('/login')
        self.assertContains(res, 'name="viewport"')

    @ddt.data(
        'EDRAAK_VIEWPORT_CHANGES',  # The feature flag should be used
        'name="viewport"',  # The viewport should be applied when the feature flag is used
        'chromeless-wrapper',  # The Edraak custom class should be used
    )
    def test_edraak_chromless_config(self, needed_string):
        """
        Use Edraak's QA recommendation by re-enabling the viewport for iPhone on chromeless.

        Testing this template is a bit harder than it seems.
        So instead we're checking the template code itself.
        """
        template = settings.PROJECT_ROOT / 'templates/courseware/courseware-chromeless.html'
        template_code = template.text()

        self.assertIn(needed_string, template_code)
