"""
Test the student dashboard view.
"""
import itertools
import json
import re
import unittest
from datetime import timedelta, datetime

import ddt
from completion.test_utils import submit_completions_for_testing, CompletionWaffleTestMixin
from django.conf import settings
from django.urls import reverse
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.utils.timezone import now
from mock import patch
from opaque_keys import InvalidKeyError

from bulk_email.models import BulkEmailFlag
from course_modes.models import CourseMode
from entitlements.tests.factories import CourseEntitlementFactory
from milestones.tests.utils import MilestonesTestCaseMixin
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.catalog.tests.factories import ProgramFactory
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.course_overviews.tests.factories import CourseOverviewFactory
from openedx.core.djangoapps.site_configuration.tests.test_util import with_site_configuration_context
from pyquery import PyQuery as pq
from openedx.core.djangoapps.schedules.config import COURSE_UPDATE_WAFFLE_FLAG
from openedx.core.djangoapps.schedules.tests.factories import ScheduleFactory
from openedx.core.djangoapps.user_authn.cookies import _get_user_info_cookie_data
from openedx.core.djangoapps.waffle_utils.testutils import override_waffle_flag
from openedx.features.course_duration_limits.models import CourseDurationLimitConfig
from openedx.features.course_experience.tests.views.helpers import add_course_mode
from student.helpers import DISABLE_UNENROLL_CERT_STATES
from student.models import CourseEnrollment, UserProfile
from student.signals import REFUND_ORDER
from student.tests.factories import CourseEnrollmentFactory, UserFactory
from util.milestones_helpers import (get_course_milestones,
                                     remove_prerequisite_course,
                                     set_prerequisite_courses)
from util.testing import UrlResetMixin
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

PASSWORD = 'test'


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class TestStudentDashboardUnenrollments(SharedModuleStoreTestCase):
    """
    Test to ensure that the student dashboard does not show the unenroll button for users with certificates.
    """
    UNENROLL_ELEMENT_ID = "#actions-item-unenroll-0"

    @classmethod
    def setUpClass(cls):
        super(TestStudentDashboardUnenrollments, cls).setUpClass()
        cls.course = CourseFactory.create()

    def setUp(self):
        """ Create a course and user, then log in. """
        super(TestStudentDashboardUnenrollments, self).setUp()
        self.user = UserFactory()
        self.enrollment = CourseEnrollmentFactory(course_id=self.course.id, user=self.user)
        self.cert_status = 'processing'
        self.client.login(username=self.user.username, password=PASSWORD)

    def mock_cert(self, _user, _course_overview):
        """ Return a preset certificate status. """
        return {
            'status': self.cert_status,
            'can_unenroll': self.cert_status not in DISABLE_UNENROLL_CERT_STATES,
            'download_url': 'fake_url',
            'linked_in_url': False,
            'grade': 100,
            'show_survey_button': False
        }

    @ddt.data(
        ('notpassing', 1),
        ('restricted', 1),
        ('processing', 1),
        ('generating', 0),
        ('downloadable', 0),
    )
    @ddt.unpack
    def test_unenroll_available(self, cert_status, unenroll_action_count):
        """ Assert that the unenroll action is shown or not based on the cert status."""
        self.cert_status = cert_status

        with patch('student.views.dashboard.cert_info', side_effect=self.mock_cert):
            response = self.client.get(reverse('dashboard'))

            self.assertEqual(pq(response.content)(self.UNENROLL_ELEMENT_ID).length, unenroll_action_count)

    @ddt.data(
        ('notpassing', 200),
        ('restricted', 200),
        ('processing', 200),
        ('generating', 400),
        ('downloadable', 400),
    )
    @ddt.unpack
    @patch.object(CourseEnrollment, 'unenroll')
    def test_unenroll_request(self, cert_status, status_code, course_enrollment):
        """ Assert that the unenroll method is called or not based on the cert status"""
        self.cert_status = cert_status

        with patch('student.views.management.cert_info', side_effect=self.mock_cert):
            with patch('lms.djangoapps.commerce.signals.handle_refund_order') as mock_refund_handler:
                REFUND_ORDER.connect(mock_refund_handler)
                response = self.client.post(
                    reverse('change_enrollment'),
                    {'enrollment_action': 'unenroll', 'course_id': self.course.id}
                )

                self.assertEqual(response.status_code, status_code)
                if status_code == 200:
                    course_enrollment.assert_called_with(self.user, self.course.id)
                    self.assertTrue(mock_refund_handler.called)
                else:
                    course_enrollment.assert_not_called()

    def test_cant_unenroll_status(self):
        """ Assert that the dashboard loads when cert_status does not allow for unenrollment"""
        with patch(
            'lms.djangoapps.certificates.models.certificate_status_for_student',
            return_value={'status': 'downloadable'},
        ):
            response = self.client.get(reverse('dashboard'))

            self.assertEqual(response.status_code, 200)

    def test_course_run_refund_status_successful(self):
        """ Assert that view:course_run_refund_status returns correct Json for successful refund call."""
        with patch('student.models.CourseEnrollment.refundable', return_value=True):
            response = self.client.get(reverse('course_run_refund_status', kwargs={'course_id': self.course.id}))

        self.assertEquals(json.loads(response.content), {'course_refundable_status': True})
        self.assertEqual(response.status_code, 200)

        with patch('student.models.CourseEnrollment.refundable', return_value=False):
            response = self.client.get(reverse('course_run_refund_status', kwargs={'course_id': self.course.id}))

        self.assertEquals(json.loads(response.content), {'course_refundable_status': False})
        self.assertEqual(response.status_code, 200)

    def test_course_run_refund_status_invalid_course_key(self):
        """ Assert that view:course_run_refund_status returns correct Json for Invalid Course Key ."""
        with patch('opaque_keys.edx.keys.CourseKey.from_string') as mock_method:
            mock_method.side_effect = InvalidKeyError('CourseKey', 'The course key used to get refund status caused \
                                                        InvalidKeyError during look up.')
            response = self.client.get(reverse('course_run_refund_status', kwargs={'course_id': self.course.id}))

        self.assertEquals(json.loads(response.content), {'course_refundable_status': ''})
        self.assertEqual(response.status_code, 406)


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class StudentDashboardTests(SharedModuleStoreTestCase, MilestonesTestCaseMixin, CompletionWaffleTestMixin):
    """
    Tests for the student dashboard.
    """

    EMAIL_SETTINGS_ELEMENT_ID = "#actions-item-email-settings-0"
    ENABLED_SIGNALS = ['course_published']
    TOMORROW = now() + timedelta(days=1)
    THREE_YEARS_FROM_NOW = now() + timedelta(days=(365 * 3))
    THREE_YEARS_AGO = now() - timedelta(days=(365 * 3))
    MOCK_SETTINGS = {
        'FEATURES': {
            'DISABLE_START_DATES': False,
            'ENABLE_MKTG_SITE': True,
            'DISABLE_SET_JWT_COOKIES_FOR_TESTS': True,
        },
        'SOCIAL_SHARING_SETTINGS': {
            'CUSTOM_COURSE_URLS': True,
            'DASHBOARD_FACEBOOK': True,
            'DASHBOARD_TWITTER': True,
        },
    }
    MOCK_SETTINGS_HIDE_COURSES = {
        'FEATURES': {
            'HIDE_DASHBOARD_COURSES_UNTIL_ACTIVATED': True,
            'DISABLE_SET_JWT_COOKIES_FOR_TESTS': True,
        }
    }

    def setUp(self):
        """
        Create a course and user, then log in.
        """
        super(StudentDashboardTests, self).setUp()
        self.user = UserFactory()
        self.client.login(username=self.user.username, password=PASSWORD)
        self.path = reverse('dashboard')

    def set_course_sharing_urls(self, set_marketing, set_social_sharing):
        """
        Set course sharing urls (i.e. social_sharing_url, marketing_url)
        """
        course_overview = self.course_enrollment.course_overview
        if set_marketing:
            course_overview.marketing_url = 'http://www.testurl.com/marketing/url/'

        if set_social_sharing:
            course_overview.social_sharing_url = 'http://www.testurl.com/social/url/'

        course_overview.save()

    def test_user_info_cookie(self):
        """
        Verify visiting the learner dashboard sets the user info cookie.
        """
        self.assertNotIn(settings.EDXMKTG_USER_INFO_COOKIE_NAME, self.client.cookies)

        request = RequestFactory().get(self.path)
        request.user = self.user
        expected = json.dumps(_get_user_info_cookie_data(request, self.user))
        self.client.get(self.path)
        actual = self.client.cookies[settings.EDXMKTG_USER_INFO_COOKIE_NAME].value
        self.assertEqual(actual, expected)

    def test_redirect_account_settings(self):
        """
        Verify if user does not have profile he/she is redirected to account_settings.
        """
        UserProfile.objects.get(user=self.user).delete()
        response = self.client.get(self.path)
        self.assertRedirects(response, reverse('account_settings'))

    @patch.multiple('django.conf.settings', **MOCK_SETTINGS)
    @ddt.data(
        *itertools.product(
            [True, False],
            [True, False],
            [ModuleStoreEnum.Type.mongo, ModuleStoreEnum.Type.split],
        )
    )
    @ddt.unpack
    def test_sharing_icons_for_future_course(self, set_marketing, set_social_sharing, modulestore_type):
        """
        Verify that the course sharing icons show up if course is starting in future and
        any of marketing or social sharing urls are set.
        """
        self.course = CourseFactory.create(start=self.TOMORROW, emit_signals=True, default_store=modulestore_type)
        self.course_enrollment = CourseEnrollmentFactory(course_id=self.course.id, user=self.user)
        self.set_course_sharing_urls(set_marketing, set_social_sharing)

        # Assert course sharing icons
        response = self.client.get(reverse('dashboard'))
        self.assertEqual('Share on Twitter' in response.content, set_marketing or set_social_sharing)
        self.assertEqual('Share on Facebook' in response.content, set_marketing or set_social_sharing)

    @patch.dict("django.conf.settings.FEATURES", {'ENABLE_PREREQUISITE_COURSES': True})
    def test_pre_requisites_appear_on_dashboard(self):
        """
        When a course has a prerequisite, the dashboard should display the prerequisite.
        If we remove the prerequisite and access the dashboard again, the prerequisite
        should not appear.
        """
        self.pre_requisite_course = CourseFactory.create(org='edx', number='999', display_name='Pre requisite Course')
        self.course = CourseFactory.create(
            org='edx',
            number='998',
            display_name='Test Course',
            pre_requisite_courses=[unicode(self.pre_requisite_course.id)]
        )
        self.course_enrollment = CourseEnrollmentFactory(course_id=self.course.id, user=self.user)

        set_prerequisite_courses(self.course.id, [unicode(self.pre_requisite_course.id)])
        response = self.client.get(reverse('dashboard'))
        self.assertIn('<div class="prerequisites">', response.content)

        remove_prerequisite_course(self.course.id, get_course_milestones(self.course.id)[0])
        response = self.client.get(reverse('dashboard'))
        self.assertNotIn('<div class="prerequisites">', response.content)

    @patch('openedx.core.djangoapps.programs.utils.get_programs')
    @patch('student.views.dashboard.get_visible_sessions_for_entitlement')
    @patch('student.views.dashboard.get_pseudo_session_for_entitlement')
    @patch.object(CourseOverview, 'get_from_id')
    def test_unfulfilled_entitlement(self, mock_course_overview, mock_pseudo_session,
                                     mock_course_runs, mock_get_programs):
        """
        When a learner has an unfulfilled entitlement, their course dashboard should have:
            - a hidden 'View Course' button
            - the text 'In order to view the course you must select a session:'
            - an unhidden course-entitlement-selection-container
            - a related programs message
        """
        program = ProgramFactory()
        CourseEntitlementFactory.create(user=self.user, course_uuid=program['courses'][0]['uuid'])
        mock_get_programs.return_value = [program]
        course_key = CourseKey.from_string('course-v1:FAKE+FA1-MA1.X+3T2017')
        mock_course_overview.return_value = CourseOverviewFactory.create(start=self.TOMORROW, id=course_key)
        mock_course_runs.return_value = [
            {
                'key': unicode(course_key),
                'enrollment_end': str(self.TOMORROW),
                'pacing_type': 'instructor_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        mock_pseudo_session.return_value = {
            'key': unicode(course_key),
            'type': 'verified'
        }
        response = self.client.get(self.path)
        self.assertIn('class="course-target-link enter-course hidden"', response.content)
        self.assertIn('You must select a session to access the course.', response.content)
        self.assertIn('<div class="course-entitlement-selection-container ">', response.content)
        self.assertIn('Related Programs:', response.content)

        # If an entitlement has already been redeemed by the user for a course run, do not let the run be selectable
        enrollment = CourseEnrollmentFactory(
            user=self.user, course_id=unicode(mock_course_overview.return_value.id), mode=CourseMode.VERIFIED
        )
        CourseEntitlementFactory.create(
            user=self.user, course_uuid=program['courses'][0]['uuid'], enrollment_course_run=enrollment
        )

        mock_course_runs.return_value = [
            {
                'key': 'course-v1:edX+toy+2012_Fall',
                'enrollment_end': str(self.TOMORROW),
                'pacing_type': 'instructor_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        response = self.client.get(self.path)
        # There should be two entitlements on the course page, one prompting for a mandatory session, but no
        # select option for the courses as there is only the single course run which has already been redeemed
        self.assertEqual(response.content.count('<li class="course-item">'), 2)
        self.assertIn('You must select a session to access the course.', response.content)
        self.assertNotIn('To access the course, select a session.', response.content)

    @patch('student.views.dashboard.get_visible_sessions_for_entitlement')
    @patch.object(CourseOverview, 'get_from_id')
    def test_unfulfilled_expired_entitlement(self, mock_course_overview, mock_course_runs):
        """
        When a learner has an unfulfilled, expired entitlement, a card should NOT appear on the dashboard.
        This use case represents either an entitlement that the user waited too long to fulfill, or an entitlement
        for which they received a refund.
        """
        CourseEntitlementFactory(
            user=self.user,
            created=self.THREE_YEARS_AGO,
            expired_at=now()
        )
        mock_course_overview.return_value = CourseOverviewFactory(start=self.TOMORROW)
        mock_course_runs.return_value = [
            {
                'key': 'course-v1:FAKE+FA1-MA1.X+3T2017',
                'enrollment_end': str(self.TOMORROW),
                'pacing_type': 'instructor_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        response = self.client.get(self.path)
        self.assertEqual(response.content.count('<li class="course-item">'), 0)

    @patch('entitlements.api.v1.views.get_course_runs_for_course')
    @patch.object(CourseOverview, 'get_from_id')
    def test_sessions_for_entitlement_course_runs(self, mock_course_overview, mock_course_runs):
        """
        When a learner has a fulfilled entitlement for a course run in the past, there should be no availableSession
        data passed to the JS view. When a learner has a fulfilled entitlement for a course run enrollment ending in the
        future, there should not be an empty availableSession variable. When a learner has a fulfilled entitlement
        for a course that doesn't have an enrollment ending, there should not be an empty availableSession variable.

        NOTE: We commented out the assertions to move this to the catalog utils test suite.
        """
        # noAvailableSessions = "availableSessions: '[]'"

        # Test an enrollment end in the past
        mocked_course_overview = CourseOverviewFactory.create(
            start=self.TOMORROW, end=self.THREE_YEARS_FROM_NOW, self_paced=True, enrollment_end=self.THREE_YEARS_AGO
        )
        mock_course_overview.return_value = mocked_course_overview
        course_enrollment = CourseEnrollmentFactory(user=self.user, course_id=unicode(mocked_course_overview.id))
        mock_course_runs.return_value = [
            {
                'key': str(mocked_course_overview.id),
                'enrollment_end': str(mocked_course_overview.enrollment_end),
                'pacing_type': 'self_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        CourseEntitlementFactory(user=self.user, enrollment_course_run=course_enrollment)
        # response = self.client.get(self.path)
        # self.assertIn(noAvailableSessions, response.content)

        # Test an enrollment end in the future sets an availableSession
        mocked_course_overview.enrollment_end = self.TOMORROW
        mocked_course_overview.save()

        mock_course_overview.return_value = mocked_course_overview
        mock_course_runs.return_value = [
            {
                'key': str(mocked_course_overview.id),
                'enrollment_end': str(mocked_course_overview.enrollment_end),
                'pacing_type': 'self_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        # response = self.client.get(self.path)
        # self.assertNotIn(noAvailableSessions, response.content)

        # Test an enrollment end that doesn't exist sets an availableSession
        mocked_course_overview.enrollment_end = None
        mocked_course_overview.save()

        mock_course_overview.return_value = mocked_course_overview
        mock_course_runs.return_value = [
            {
                'key': str(mocked_course_overview.id),
                'enrollment_end': None,
                'pacing_type': 'self_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        # response = self.client.get(self.path)
        # self.assertNotIn(noAvailableSessions, response.content)

    @patch('openedx.core.djangoapps.programs.utils.get_programs')
    @patch('student.views.dashboard.get_visible_sessions_for_entitlement')
    @patch.object(CourseOverview, 'get_from_id')
    def test_fulfilled_entitlement(self, mock_course_overview, mock_course_runs, mock_get_programs):
        """
        When a learner has a fulfilled entitlement, their course dashboard should have:
            - exactly one course item, meaning it:
                - has an entitlement card
                - does NOT have a course card referencing the selected session
            - an unhidden Change or Leave Session button
            - a related programs message
        """
        mocked_course_overview = CourseOverviewFactory(
            start=self.TOMORROW, self_paced=True, enrollment_end=self.TOMORROW
        )
        mock_course_overview.return_value = mocked_course_overview
        course_enrollment = CourseEnrollmentFactory(user=self.user, course_id=unicode(mocked_course_overview.id))
        mock_course_runs.return_value = [
            {
                'key': str(mocked_course_overview.id),
                'enrollment_end': str(mocked_course_overview.enrollment_end),
                'pacing_type': 'self_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        entitlement = CourseEntitlementFactory(user=self.user, enrollment_course_run=course_enrollment)
        program = ProgramFactory()
        program['courses'][0]['course_runs'] = [{'key': unicode(mocked_course_overview.id)}]
        program['courses'][0]['uuid'] = entitlement.course_uuid
        mock_get_programs.return_value = [program]
        response = self.client.get(self.path)
        self.assertEqual(response.content.count('<li class="course-item">'), 1)
        self.assertIn('<button class="change-session btn-link "', response.content)
        self.assertIn('Related Programs:', response.content)

    @patch('openedx.core.djangoapps.programs.utils.get_programs')
    @patch('student.views.dashboard.get_visible_sessions_for_entitlement')
    @patch.object(CourseOverview, 'get_from_id')
    def test_fulfilled_expired_entitlement(self, mock_course_overview, mock_course_runs, mock_get_programs):
        """
        When a learner has a fulfilled entitlement that is expired, their course dashboard should have:
            - exactly one course item, meaning it:
                - has an entitlement card
            - Message that the learner can no longer change sessions
            - a related programs message
        """
        mocked_course_overview = CourseOverviewFactory(
            start=self.TOMORROW, self_paced=True, enrollment_end=self.TOMORROW
        )
        mock_course_overview.return_value = mocked_course_overview
        course_enrollment = CourseEnrollmentFactory(user=self.user, course_id=unicode(mocked_course_overview.id), created=self.THREE_YEARS_AGO)
        mock_course_runs.return_value = [
            {
                'key': str(mocked_course_overview.id),
                'enrollment_end': str(mocked_course_overview.enrollment_end),
                'pacing_type': 'self_paced',
                'type': 'verified',
                'status': 'published'
            }
        ]
        entitlement = CourseEntitlementFactory(user=self.user, enrollment_course_run=course_enrollment, created=self.THREE_YEARS_AGO)
        program = ProgramFactory()
        program['courses'][0]['course_runs'] = [{'key': unicode(mocked_course_overview.id)}]
        program['courses'][0]['uuid'] = entitlement.course_uuid
        mock_get_programs.return_value = [program]
        response = self.client.get(self.path)
        self.assertEqual(response.content.count('<li class="course-item">'), 1)
        self.assertIn('You can no longer change sessions.', response.content)
        self.assertIn('Related Programs:', response.content)

    @patch('openedx.core.djangoapps.catalog.utils.get_course_runs_for_course')
    @patch.object(BulkEmailFlag, 'feature_enabled')
    def test_email_settings_fulfilled_entitlement(self, mock_email_feature, mock_get_course_runs):
        """
        Assert that the Email Settings action is shown when the user has a fulfilled entitlement.
        """
        mock_email_feature.return_value = True
        course_overview = CourseOverviewFactory(
            start=self.TOMORROW, self_paced=True, enrollment_end=self.TOMORROW
        )
        course_enrollment = CourseEnrollmentFactory(user=self.user)
        entitlement = CourseEntitlementFactory(user=self.user, enrollment_course_run=course_enrollment)
        course_runs = [{
            'key': unicode(course_overview.id),
            'uuid': entitlement.course_uuid
        }]
        mock_get_course_runs.return_value = course_runs

        response = self.client.get(self.path)
        self.assertEqual(pq(response.content)(self.EMAIL_SETTINGS_ELEMENT_ID).length, 1)

    @patch.object(CourseOverview, 'get_from_id')
    @patch.object(BulkEmailFlag, 'feature_enabled')
    def test_email_settings_unfulfilled_entitlement(self, mock_email_feature, mock_course_overview):
        """
        Assert that the Email Settings action is not shown when the entitlement is not fulfilled.
        """
        mock_email_feature.return_value = True
        mock_course_overview.return_value = CourseOverviewFactory(start=self.TOMORROW)
        CourseEntitlementFactory(user=self.user)
        response = self.client.get(self.path)
        self.assertEqual(pq(response.content)(self.EMAIL_SETTINGS_ELEMENT_ID).length, 0)

    @patch.multiple('django.conf.settings', **MOCK_SETTINGS_HIDE_COURSES)
    def test_hide_dashboard_courses_until_activated(self):
        """
        Verify that when the HIDE_DASHBOARD_COURSES_UNTIL_ACTIVATED feature is enabled,
        inactive users don't see the Courses list, but active users still do.
        """
        # Ensure active users see the course list
        self.assertTrue(self.user.is_active)
        response = self.client.get(reverse('dashboard'))
        self.assertIn('You are not enrolled in any courses yet.', response.content)

        # Ensure inactive users don't see the course list
        self.user.is_active = False
        self.user.save()
        response = self.client.get(reverse('dashboard'))
        self.assertNotIn('You are not enrolled in any courses yet.', response.content)

    def test_show_empty_dashboard_message(self):
        """
        Verify that when the EMPTY_DASHBOARD_MESSAGE feature is set,
        its text is displayed in an empty courses list.
        """
        empty_dashboard_message = "Check out our lovely <i>free</i> courses!"
        response = self.client.get(reverse('dashboard'))
        self.assertIn('You are not enrolled in any courses yet.', response.content)
        self.assertNotIn(empty_dashboard_message, response.content)

        with with_site_configuration_context(configuration={
            "EMPTY_DASHBOARD_MESSAGE": empty_dashboard_message,
        }):
            response = self.client.get(reverse('dashboard'))
            self.assertIn('You are not enrolled in any courses yet.', response.content)
            self.assertIn(empty_dashboard_message, response.content)

    @staticmethod
    def _remove_whitespace_from_html_string(html):
        return ''.join(html.split())

    @staticmethod
    def _pull_course_run_from_course_key(course_key_string):
        search_results = re.search(r'Run_[0-9]+$', course_key_string)
        assert search_results
        course_run_string = search_results.group(0).replace('_', ' ')
        return course_run_string

    @staticmethod
    def _get_html_for_view_course_button(course_key_string, course_run_string):
        return '''
            <a href="/courses/{course_key}/course/"
               class="course-target-link enter-course"
               data-course-key="{course_key}">
              View Course
              <span class="sr">
                &nbsp;{course_run}
              </span>
            </a>
        '''.format(course_key=course_key_string, course_run=course_run_string)

    @staticmethod
    def _get_html_for_resume_course_button(course_key_string, resume_block_key_string, course_run_string):
        return '''
            <a href="/courses/{course_key}/jump_to/{url_to_block}"
               class="course-target-link enter-course"
               data-course-key="{course_key}">
              Resume Course
              <span class="sr">
                &nbsp;{course_run}
              </span>
            </a>
        '''.format(
            course_key=course_key_string,
            url_to_block=resume_block_key_string,
            course_run=course_run_string
        )

    @staticmethod
    def _get_html_for_entitlement_button(course_key_string):
        return'''
            <div class="course-info">
            <span class="info-university">{org} - </span>
            <span class="info-course-id">{course}</span>
            <span class="info-date-block-container">
            <button class="change-session btn-link ">Change or Leave Session</button>
            </span>
            </div>
        '''.format(
            org=course_key_string.split('/')[0],
            course=course_key_string.split('/')[1]
        )

    def test_view_course_appears_on_dashboard(self):
        """
        When a course doesn't have completion data, its course card should
        display a "View Course" button.
        """
        self.override_waffle_switch(True)

        course = CourseFactory.create()
        CourseEnrollmentFactory.create(
            user=self.user,
            course_id=course.id
        )

        response = self.client.get(reverse('dashboard'))

        course_key_string = str(course.id)
        # No completion data means there's no block from which to resume.
        resume_block_key_string = ''
        course_run_string = self._pull_course_run_from_course_key(course_key_string)

        view_button_html = self._get_html_for_view_course_button(
            course_key_string,
            course_run_string
        )
        resume_button_html = self._get_html_for_resume_course_button(
            course_key_string,
            resume_block_key_string,
            course_run_string
        )

        view_button_html = self._remove_whitespace_from_html_string(view_button_html)
        resume_button_html = self._remove_whitespace_from_html_string(resume_button_html)
        dashboard_html = self._remove_whitespace_from_html_string(response.content)

        self.assertIn(
            view_button_html,
            dashboard_html
        )
        self.assertNotIn(
            resume_button_html,
            dashboard_html
        )

    def test_resume_course_appears_on_dashboard(self):
        """
        When a course has completion data, its course card should display a
        "Resume Course" button.
        """
        self.override_waffle_switch(True)

        course = CourseFactory.create()
        CourseEnrollmentFactory.create(
            user=self.user,
            course_id=course.id
        )

        course_key = course.id
        block_keys = [
            ItemFactory.create(
                category='video',
                parent_location=course.location,
                display_name='Video {0}'.format(unicode(number))
            ).location
            for number in xrange(5)
        ]

        submit_completions_for_testing(self.user, course_key, block_keys)

        response = self.client.get(reverse('dashboard'))

        course_key_string = str(course_key)
        resume_block_key_string = str(block_keys[-1])
        course_run_string = self._pull_course_run_from_course_key(course_key_string)

        view_button_html = self._get_html_for_view_course_button(
            course_key_string,
            course_run_string
        )
        resume_button_html = self._get_html_for_resume_course_button(
            course_key_string,
            resume_block_key_string,
            course_run_string
        )

        view_button_html = self._remove_whitespace_from_html_string(view_button_html)
        resume_button_html = self._remove_whitespace_from_html_string(resume_button_html)
        dashboard_html = self._remove_whitespace_from_html_string(response.content)

        self.assertIn(
            resume_button_html,
            dashboard_html
        )
        self.assertNotIn(
            view_button_html,
            dashboard_html
        )

    @override_waffle_flag(COURSE_UPDATE_WAFFLE_FLAG, True)
    def test_content_gating_course_card_changes(self):
        """
        When a course is expired, the links on the course card should be removed.
        Links will be removed from the course title, course image and button (View Course/Resume Course).
        The course card should have an access expired message.
        """
        CourseDurationLimitConfig.objects.create(enabled=True, enabled_as_of=datetime(2018, 1, 1))
        self.override_waffle_switch(True)

        course = CourseFactory.create(start=self.THREE_YEARS_AGO)
        add_course_mode(course, upgrade_deadline_expired=False)
        enrollment = CourseEnrollmentFactory.create(
            user=self.user,
            course_id=course.id
        )
        schedule = ScheduleFactory(start=self.THREE_YEARS_AGO, enrollment=enrollment)

        response = self.client.get(reverse('dashboard'))
        dashboard_html = self._remove_whitespace_from_html_string(response.content)
        access_expired_substring = 'Accessexpired'
        course_link_class = 'course-target-link'

        self.assertNotIn(
            course_link_class,
            dashboard_html
        )

        self.assertIn(
            access_expired_substring,
            dashboard_html
        )

    def test_dashboard_with_resume_buttons_and_view_buttons(self):
        '''
        The Test creates a four-course-card dashboard. The user completes course
        blocks in the even-numbered course cards. The test checks that courses
        with completion data have course cards with "Resume Course" buttons;
        those without have "View Course" buttons.

        '''
        self.override_waffle_switch(True)

        isEven = lambda n: n % 2 == 0

        num_course_cards = 4

        html_for_view_buttons = []
        html_for_resume_buttons = []
        html_for_entitlement = []

        for i in range(num_course_cards):

            course = CourseFactory.create()
            course_enrollment = CourseEnrollmentFactory(
                user=self.user,
                course_id=course.id
            )

            course_key = course_enrollment.course_id
            course_key_string = str(course_key)

            if i == 1:
                CourseEntitlementFactory.create(user=self.user, enrollment_course_run=course_enrollment)

            else:
                last_completed_block_string = ''
                course_run_string = self._pull_course_run_from_course_key(
                    course_key_string)

            # Submit completed course blocks in even-numbered courses.
            if isEven(i):
                block_keys = [
                    ItemFactory.create(
                        category='video',
                        parent_location=course.location,
                        display_name='Video {0}'.format(unicode(number))
                    ).location
                    for number in xrange(5)
                ]
                last_completed_block_string = str(block_keys[-1])

                submit_completions_for_testing(self.user, course_key, block_keys)

            html_for_view_buttons.append(
                self._get_html_for_view_course_button(
                    course_key_string,
                    course_run_string
                )
            )
            html_for_resume_buttons.append(
                self._get_html_for_resume_course_button(
                    course_key_string,
                    last_completed_block_string,
                    course_run_string
                )
            )
            html_for_entitlement.append(
                self._get_html_for_entitlement_button(
                    course_key_string
                )
            )

        response = self.client.get(reverse('dashboard'))

        html_for_view_buttons = [
            self._remove_whitespace_from_html_string(button)
            for button in html_for_view_buttons
        ]
        html_for_resume_buttons = [
            self._remove_whitespace_from_html_string(button)
            for button in html_for_resume_buttons
        ]
        html_for_entitlement = [
            self._remove_whitespace_from_html_string(button)
            for button in html_for_entitlement
        ]

        dashboard_html = self._remove_whitespace_from_html_string(response.content)

        for i in range(num_course_cards):
            expected_button = None
            unexpected_button = None

            if i == 1:
                expected_button = html_for_entitlement[i]
                unexpected_button = html_for_view_buttons[i] + html_for_resume_buttons[i]

            elif isEven(i):
                expected_button = html_for_resume_buttons[i]
                unexpected_button = html_for_view_buttons[i] + html_for_entitlement[i]
            else:
                expected_button = html_for_view_buttons[i]
                unexpected_button = html_for_resume_buttons[i] + html_for_entitlement[i]

            self.assertIn(
                expected_button,
                dashboard_html
            )
            self.assertNotIn(
                unexpected_button,
                dashboard_html
            )


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
@override_settings(BRANCH_IO_KEY='test_key')
class TextMeTheAppViewTests(UrlResetMixin, TestCase):
    """ Tests for the TextMeTheAppView. """

    def test_text_me_the_app(self):
        response = self.client.get(reverse('text_me_the_app'))
        self.assertContains(response, 'Send me a text with the link')
