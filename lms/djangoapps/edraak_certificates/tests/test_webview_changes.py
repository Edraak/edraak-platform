"""Tests for changes on certificates by Edraak"""

from django.test.utils import override_settings

from lms.djangoapps.certificates.api import get_certificate_url
from lms.djangoapps.certificates.models import CertificateTemplate

from lms.djangoapps.certificates.tests.test_webview_views import CommonCertificatesTestCase
from openedx.core.djangoapps.models.course_details import CourseDetails


class TestEdraakCertificate(CommonCertificatesTestCase):
    @staticmethod
    def _create_edraak_test_template():
        """
        Creates a custom certificate template that is used for Edraak changes
        """
        template_html = """
            <%namespace name='static' file='static_content.html'/>
            <html>
            <body>
                <b>Edraak Template</b>
                course_description: ${course_description}
            </body>
            </html>
        """
        template = CertificateTemplate(
            name='custom template',
            template=template_html,
            organization_id=None,
            course_key=None,
            mode='honor',
            is_active=True,
            language=None
        )
        template.save()

    @override_settings(FEATURES={
        "CUSTOM_CERTIFICATE_TEMPLATES_ENABLED": True,
        "CERTIFICATES_HTML_VIEW": True
    })
    def test_changes_on_webview(self):
        # Prepare attributes to check for
        CourseDetails.update_about_item(self.course, 'short_description', 'Edraak Test Description', self.user.id)

        # Creating a certificate
        self._add_course_certificates(count=1, signatory_count=2)
        self._create_edraak_test_template()
        test_url = get_certificate_url(
            user_id=self.user.id,
            course_id=unicode(self.course.id)
        )

        # Getting certificate as HTML
        response = self.client.get(test_url)

        # Verifying contents
        self.assertContains(response, 'Edraak Template')
        self.assertContains(response, 'course_description: Edraak Test Description')
