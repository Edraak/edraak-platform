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
class DashboardCertificateButtonTestCase(ModuleStoreLoggedInTestCase):
    LOGIN_STAFF = False
    ENROLL_USER = True
    BUTTON_TEXT = 'Issue Certificate'
    ADDITIONAL_CLASS = 'course-actions-with-edraak-certificates'

    def setUp(self):
        super(DashboardCertificateButtonTestCase, self).setUp()
        self.button_link = reverse('edraak_certificates:issue', args=[self.course.id])

    def create_course(self):
        # Make the `may_certify()` true!
        past_week = datetime.now(pytz.UTC) - timedelta(days=7)
        course = CourseFactory.create(
            start=past_week,
            end=past_week,
        )

        from edraak_certificates.utils import STATIC_DIR
        from django.core.files.uploadedfile import SimpleUploadedFile

        # Enforce a DB logo
        logo_file_name = 'moe.png'
        with open(os.path.join(STATIC_DIR, logo_file_name), 'rb') as logo:
            OrganizationFactory.create(
                short_name=course.org,
                logo=SimpleUploadedFile(logo_file_name, content=logo.read()),
            )

        return course

    @patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_DASHBOARD_BUTTON=True)
    def test_enabled_certificate_button(self):
        res = self.client.get(reverse('dashboard'))
        self.assertContains(res, self.course.display_name)  # Sanity check
        self.assertContains(res, self.BUTTON_TEXT, msg_prefix='Should show the Edraak Certificate button')
        self.assertContains(res, self.ADDITIONAL_CLASS, msg_prefix='Should show the extra CSS')
        self.assertContains(res, self.button_link, msg_prefix='Should link to the `issue` view')

    @patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_DASHBOARD_BUTTON=False)
    def test_disabled_certificate_button(self):
        res = self.client.get(reverse('dashboard'))
        self.assertContains(res, self.course.display_name)  # Sanity check
        self.assertNotContains(res, self.BUTTON_TEXT, msg_prefix='Should NOT show the Edraak Certificate button')
        self.assertNotContains(res, self.ADDITIONAL_CLASS, msg_prefix='Should NOT show the extra CSS')
        self.assertNotContains(res, self.button_link, msg_prefix='Should NOT show a link to the `issue` view')

    @ddt.data('preview_png', 'download_pdf')
    def test_user_for_png_and_pdf(self, view_name):
        view_full_name = 'edraak_certificates:{view_name}'.format(view_name=view_name)
        url = reverse(view_full_name, args=[self.course.id])

        # When the student passes
        with patch('edraak_certificates.views.is_student_pass', return_value=True):
            succeeded_res = self.client.get(url)
        self.assertEquals(200, succeeded_res.status_code)  # Should generate the certificate for the successful student

        # Should provide a correct content-type
        self.assertIn(succeeded_res['Content-Type'], ['application/octet-stream', 'image/png'])

        # When the student fails!
        with patch('edraak_certificates.views.is_student_pass', return_value=False):
            failed_res = self.client.get(url)
        self.assertEquals(404, failed_res.status_code)  # Should just throw a 404 error when the student didn't pass


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
