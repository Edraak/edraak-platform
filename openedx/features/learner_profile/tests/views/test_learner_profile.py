# -*- coding: utf-8 -*-
""" Tests for student profile views. """

import datetime
import ddt
import mock

from lms.djangoapps.certificates.tests.factories import GeneratedCertificateFactory
from lms.djangoapps.certificates.api import is_passing_status
from lms.envs.test import CREDENTIALS_PUBLIC_SERVICE_URL
from course_modes.models import CourseMode
from django.conf import settings
from django.urls import reverse
from django.test.client import RequestFactory
from opaque_keys.edx.locator import CourseLocator
from openedx.features.learner_profile.views.learner_profile import learner_profile_context
from student.tests.factories import CourseEnrollmentFactory, UserFactory
from util.testing import UrlResetMixin
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory


@ddt.ddt
class LearnerProfileViewTest(UrlResetMixin, ModuleStoreTestCase):
    """ Tests for the student profile view. """

    USERNAME = "username"
    OTHER_USERNAME = "other_user"
    PASSWORD = "password"
    DOWNLOAD_URL = "http://www.example.com/certificate.pdf"
    CONTEXT_DATA = [
        'default_public_account_fields',
        'accounts_api_url',
        'preferences_api_url',
        'account_settings_page_url',
        'has_preferences_access',
        'own_profile',
        'country_options',
        'language_options',
        'account_settings_data',
        'preferences_data',
    ]

    def setUp(self):
        super(LearnerProfileViewTest, self).setUp()
        self.user = UserFactory.create(username=self.USERNAME, password=self.PASSWORD)
        self.other_user = UserFactory.create(username=self.OTHER_USERNAME, password=self.PASSWORD)
        self.client.login(username=self.USERNAME, password=self.PASSWORD)
        self.course = CourseFactory.create(
            start=datetime.datetime(2013, 9, 16, 7, 17, 28),
            end=datetime.datetime.now(),
            certificate_available_date=datetime.datetime.now(),
        )

    def test_context(self):
        """
        Verify learner profile page context data.
        """
        request = RequestFactory().get('/url')
        request.user = self.user

        context = learner_profile_context(request, self.USERNAME, self.user.is_staff)

        self.assertEqual(
            context['data']['default_public_account_fields'],
            settings.ACCOUNT_VISIBILITY_CONFIGURATION['public_fields']
        )

        self.assertEqual(
            context['data']['accounts_api_url'],
            reverse("accounts_api", kwargs={'username': self.user.username})
        )

        self.assertEqual(
            context['data']['preferences_api_url'],
            reverse('preferences_api', kwargs={'username': self.user.username})
        )

        self.assertEqual(
            context['data']['profile_image_upload_url'],
            reverse("profile_image_upload", kwargs={'username': self.user.username})
        )

        self.assertEqual(
            context['data']['profile_image_remove_url'],
            reverse('profile_image_remove', kwargs={'username': self.user.username})
        )

        self.assertEqual(
            context['data']['profile_image_max_bytes'],
            settings.PROFILE_IMAGE_MAX_BYTES
        )

        self.assertEqual(
            context['data']['profile_image_min_bytes'],
            settings.PROFILE_IMAGE_MIN_BYTES
        )

        self.assertEqual(context['data']['account_settings_page_url'], reverse('account_settings'))

        for attribute in self.CONTEXT_DATA:
            self.assertIn(attribute, context['data'])

    def test_view(self):
        """
        Verify learner profile page view.
        """
        profile_path = reverse('learner_profile', kwargs={'username': self.USERNAME})
        response = self.client.get(path=profile_path)

        for attribute in self.CONTEXT_DATA:
            self.assertIn(attribute, response.content)

    def test_records_link(self):
        profile_path = reverse('learner_profile', kwargs={'username': self.USERNAME})
        response = self.client.get(path=profile_path)
        self.assertContains(response, '<a href="{}/records/">'.format(CREDENTIALS_PUBLIC_SERVICE_URL))

    def test_undefined_profile_page(self):
        """
        Verify that a 404 is returned for a non-existent profile page.
        """
        profile_path = reverse('learner_profile', kwargs={'username': "no_such_user"})
        response = self.client.get(path=profile_path)
        self.assertEqual(404, response.status_code)

    def _create_certificate(self, course_key=None, enrollment_mode=CourseMode.HONOR, status='downloadable'):
        """Simulate that the user has a generated certificate. """
        CourseEnrollmentFactory.create(user=self.user, course_id=self.course.id, mode=enrollment_mode)
        return GeneratedCertificateFactory(
            user=self.user,
            course_id=course_key or self.course.id,
            mode=enrollment_mode,
            download_url=self.DOWNLOAD_URL,
            status=status,
        )

    @ddt.data(CourseMode.HONOR, CourseMode.PROFESSIONAL, CourseMode.VERIFIED)
    def test_certificate_visibility(self, cert_mode):
        """
        Verify that certificates are displayed with the correct card mode.
        """
        # Add new certificate
        cert = self._create_certificate(enrollment_mode=cert_mode)
        cert.save()

        response = self.client.get('/u/{username}'.format(username=self.user.username))

        self.assertContains(response, 'card certificate-card mode-{cert_mode}'.format(cert_mode=cert_mode))

    @ddt.data(
        ['downloadable', True],
        ['notpassing', False],
    )
    @ddt.unpack
    def test_certificate_status_visibility(self, status, is_passed_status):
        """
        Verify that certificates are only displayed for passing status.
        """
        # Add new certificate
        cert = self._create_certificate(status=status)
        cert.save()

        # Ensure that this test is actually using both passing and non-passing certs.
        self.assertEqual(is_passing_status(cert.status), is_passed_status)

        response = self.client.get('/u/{username}'.format(username=self.user.username))

        if is_passed_status:
            self.assertContains(response, 'card certificate-card mode-{cert_mode}'.format(cert_mode=cert.mode))
        else:
            self.assertNotContains(response, 'card certificate-card mode-{cert_mode}'.format(cert_mode=cert.mode))

    def test_certificate_for_missing_course(self):
        """
        Verify that a certificate is not shown for a missing course.
        """
        # Add new certificate
        cert = self._create_certificate(course_key=CourseLocator.from_string('course-v1:edX+INVALID+1'))
        cert.save()

        response = self.client.get('/u/{username}'.format(username=self.user.username))

        self.assertNotContains(response, 'card certificate-card mode-{cert_mode}'.format(cert_mode=cert.mode))

    @ddt.data(True, False)
    def test_no_certificate_visibility(self, own_profile):
        """
        Verify that the 'You haven't earned any certificates yet.' well appears on the user's
        own profile when they do not have certificates and does not appear when viewing
        another user that does not have any certificates.
        """
        profile_username = self.user.username if own_profile else self.other_user.username
        response = self.client.get('/u/{username}'.format(username=profile_username))

        if own_profile:
            self.assertContains(response, 'You haven&#39;t earned any certificates yet.')
        else:
            self.assertNotContains(response, 'You haven&#39;t earned any certificates yet.')

    @ddt.data(True, False)
    def test_explore_courses_visibility(self, courses_browsable):
        with mock.patch.dict('django.conf.settings.FEATURES', {'COURSES_ARE_BROWSABLE': courses_browsable}):
            response = self.client.get('/u/{username}'.format(username=self.user.username))
            if courses_browsable:
                self.assertContains(response, 'Explore New Courses')
            else:
                self.assertNotContains(response, 'Explore New Courses')

    def test_certificate_for_visibility_for_not_viewable_course(self):
        """
        Verify that a certificate is not shown if certificate are not viewable to users.
        """
        # add new course with certificate_available_date is future date.
        course = CourseFactory.create(
            certificate_available_date=datetime.datetime.now() + datetime.timedelta(days=5)
        )

        cert = self._create_certificate(course_key=course.id)
        cert.save()

        response = self.client.get('/u/{username}'.format(username=self.user.username))

        self.assertNotContains(response, 'card certificate-card mode-{cert_mode}'.format(cert_mode=cert.mode))
