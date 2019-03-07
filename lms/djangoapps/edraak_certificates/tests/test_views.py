"""
Tests for Edraak Certificates.
"""
from datetime import datetime, timedelta
import ddt
from django.core.urlresolvers import reverse
from django.conf import settings
from django.test import TestCase
from mock import patch
from organizations.tests.factories import OrganizationFactory
import os.path
import pytz

from edraak_tests.tests.helpers import ModuleStoreLoggedInTestCase
from xmodule.modulestore.tests.factories import CourseFactory


@ddt.ddt
class CertificateUrlsTest(TestCase):
    """
    Sanity checks for the environment settings
    """
    @ddt.data('issue', 'preview', 'download_pdf', 'preview_png')
    def test_view_urls(self, view_name):
        course_key = 'edx/Demo/2014'
        view_full_name = 'edraak_certificates:{view_name}'.format(view_name=view_name)

        url = reverse(view_full_name, args=[course_key])
        self.assertIn('certificates', url)
        self.assertIn(course_key, url)


@ddt.ddt
class AnonymousTestCase(ModuleStoreLoggedInTestCase):
    def setUp(self):
        super(AnonymousTestCase, self).setUp()
        self.client.logout()

    @ddt.data('issue', 'preview', 'download_pdf', 'preview_png')
    def test_logged_out_redirect(self, view_name):
        view_full_name = 'edraak_certificates:{view_name}'.format(view_name=view_name)
        url = reverse(view_full_name, args=[self.course.id])

        res = self.client.get(url)
        self.assertRedirects(res, '/login?next={}'.format(url),
                             msg_prefix='Ensures the page is not accessible for anonymous users')


@ddt.ddt
class StaffTestCase(ModuleStoreLoggedInTestCase):
    LOGIN_STAFF = True
    ENROLL_USER = True

    def create_course(self):
        # Use the legacy logos, with a sponsor
        return CourseFactory.create(
            org='BritishCouncil',
            number='Eng100',
            run='T4_2015',
        )

    def get_cert_url(self, view_name):
        view_full_name = 'edraak_certificates:{view_name}'.format(view_name=view_name)
        return reverse(view_full_name, args=[self.course.id])

    def test_certificate_waiting_page(self):
        view_url = self.get_cert_url('preview')

        res = self.client.get(self.get_cert_url('issue'))

        self.assertContains(res, 'http-equiv="refresh"',
                            msg_prefix='The page should redirect to the `view` certificate page')
        self.assertContains(res, 'Please wait', msg_prefix='The page should show the grader loading and a message')
        self.assertContains(res, view_url, msg_prefix='The page should have the `view` page URL')

    def test_preview_page(self):
        preview_url = self.get_cert_url('preview_png')
        download_url = self.get_cert_url('download_pdf')

        res = self.client.get(self.get_cert_url('preview'))
        self.assertContains(res, download_url, msg_prefix='Should have the link in the download button')
        self.assertContains(res, preview_url, msg_prefix='Should show the preview image of the certificate')

        # Just in case!
        self.assertNotContains(res, 'http-equiv="refresh"', msg_prefix='Should NOT redirect to another page')

    @patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=False)
    def test_fail_page(self):
        """
        Although this shouldn't appear to `staff` users. But we're testing it here anyway!
        """
        preview_url = self.get_cert_url('preview_png')
        download_url = self.get_cert_url('download_pdf')
        dashboard_url = reverse('dashboard')

        # Should show the fail page
        res = self.client.get(self.get_cert_url('preview'))

        self.assertContains(res, 'Unfortunately, you have',
                            msg_prefix='Should clarify the why there is not certificate')

        self.assertNotContains(res, download_url, msg_prefix='Should NOT have a download link (button)')
        self.assertNotContains(res, preview_url, msg_prefix='Should NOT show a certificate preview image')

        self.assertContains(res, dashboard_url, msg_prefix='Should provide option to go to dashboard')

        # Developers: Could go to courseware page instead! Not sure about the correct logic.
        self.assertContains(res, 'http-equiv="refresh"', msg_prefix='Should redirect to, dashboard')

    def test_png(self):
        res = self.client.get(self.get_cert_url('preview_png'))

        self.assertEquals(res.status_code, 200)
        self.assertIsNotNone(res.content)
        self.assertEquals(res['Content-Type'], 'image/png')
        self.assertGreater(res['Content-Length'], 0)  # Should have some content!

    def test_pdf(self):
        res = self.client.get(self.get_cert_url('download_pdf'))

        self.assertEquals(res.status_code, 200)
        self.assertIsNotNone(res.content)
        self.assertEquals(res['Content-Type'], 'application/octet-stream')
        self.assertGreater(res['Content-Length'], 0)  # Should have some content!

        # Provide a basic name for the file
        self.assertEquals(res['Content-Disposition'], 'attachment; filename=Edraak-Certificate.pdf')
