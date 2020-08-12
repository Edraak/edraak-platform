"""
Tests for the recently enrolled messaging within the Dashboard.
"""
import datetime
import unittest

import ddt
from django.conf import settings
from django.urls import reverse
from django.utils.timezone import now
from opaque_keys.edx import locator
from pytz import UTC

from common.test.utils import XssTestMixin
from course_modes.tests.factories import CourseModeFactory
from openedx.core.djangoapps.site_configuration.tests.test_util import with_site_configuration_context
from shoppingcart.models import DonationConfiguration
from student.models import CourseEnrollment, DashboardConfiguration
from student.tests.factories import UserFactory
from student.views import get_course_enrollments
from student.views.dashboard import _get_recently_enrolled_courses
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
@ddt.ddt
class TestRecentEnrollments(ModuleStoreTestCase, XssTestMixin):
    """
    Unit tests for getting the list of courses for a logged in user
    """
    shard = 3
    PASSWORD = 'test'

    def setUp(self):
        """
        Add a student
        """
        super(TestRecentEnrollments, self).setUp()
        self.student = UserFactory()
        self.student.set_password(self.PASSWORD)
        self.student.save()

        # Old Course
        old_course_location = locator.CourseLocator('Org0', 'Course0', 'Run0')
        __, enrollment = self._create_course_and_enrollment(old_course_location)
        enrollment.created = datetime.datetime(1900, 12, 31, 0, 0, 0, 0, tzinfo=UTC)
        enrollment.save()

        # New Course
        course_location = locator.CourseLocator('Org1', 'Course1', 'Run1')
        self.course, self.enrollment = self._create_course_and_enrollment(course_location)

    def _create_course_and_enrollment(self, course_location):
        """ Creates a course and associated enrollment. """
        course = CourseFactory.create(
            org=course_location.org,
            number=course_location.course,
            run=course_location.run
        )
        enrollment = CourseEnrollment.enroll(self.student, course.id)
        return course, enrollment

    def _configure_message_timeout(self, timeout):
        """Configure the amount of time the enrollment message will be displayed. """
        config = DashboardConfiguration(recent_enrollment_time_delta=timeout)
        config.save()

    def test_recently_enrolled_courses(self):
        """
        Test if the function for filtering recent enrollments works appropriately.
        """
        self._configure_message_timeout(60)

        # get courses through iterating all courses
        courses_list = list(get_course_enrollments(self.student, None, []))
        self.assertEqual(len(courses_list), 2)

        recent_course_list = _get_recently_enrolled_courses(courses_list)
        self.assertEqual(len(recent_course_list), 1)

    def test_zero_second_delta(self):
        """
        Tests that the recent enrollment list is empty if configured to zero seconds.
        """
        self._configure_message_timeout(0)
        courses_list = list(get_course_enrollments(self.student, None, []))
        self.assertEqual(len(courses_list), 2)

        recent_course_list = _get_recently_enrolled_courses(courses_list)
        self.assertEqual(len(recent_course_list), 0)

    def test_enrollments_sorted_most_recent(self):
        """
        Test that the list of newly created courses are properly sorted to show the most
        recent enrollments first.
        Also test recent enrollment message rendered appropriately for more than two courses.
        """
        self._configure_message_timeout(600)

        # Create a number of new enrollments and courses, and force their creation behind
        # the first enrollment
        courses = []
        for idx, seconds_past in zip(range(2, 6), [5, 10, 15, 20]):
            course_location = locator.CourseLocator(
                'Org{num}'.format(num=idx),
                'Course{num}'.format(num=idx),
                'Run{num}'.format(num=idx)
            )
            course, enrollment = self._create_course_and_enrollment(course_location)
            enrollment.created = now() - datetime.timedelta(seconds=seconds_past)
            enrollment.save()
            courses.append(course)

        courses_list = list(get_course_enrollments(self.student, None, []))
        self.assertEqual(len(courses_list), 6)

        recent_course_list = _get_recently_enrolled_courses(courses_list)
        self.assertEqual(len(recent_course_list), 5)

        self.assertEqual(recent_course_list[1].course.id, courses[0].id)
        self.assertEqual(recent_course_list[2].course.id, courses[1].id)
        self.assertEqual(recent_course_list[3].course.id, courses[2].id)
        self.assertEqual(recent_course_list[4].course.id, courses[3].id)

        self.client.login(username=self.student.username, password=self.PASSWORD)
        response = self.client.get(reverse("dashboard"))

        # verify recent enrollment message
        self.assertContains(
            response,
            'Thank you for enrolling in:'.format(course_name=self.course.display_name)
        )
        self.assertContains(
            response,
            ', '.join(enrollment.course.display_name for enrollment in recent_course_list)
        )

    def test_dashboard_rendering_with_single_course(self):
        """
        Tests that the dashboard renders the recent enrollment message appropriately for single course.
        """
        self._configure_message_timeout(600)
        self.client.login(username=self.student.username, password=self.PASSWORD)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(
            response,
            "Thank you for enrolling in {course_name}".format(course_name=self.course.display_name)
        )

    def test_dashboard_rendering_with_two_courses(self):
        """
        Tests that the dashboard renders the recent enrollment message appropriately for two courses.
        """
        self._configure_message_timeout(600)
        course_location = locator.CourseLocator(
            'Org2',
            'Course2',
            'Run2'
        )
        course, _ = self._create_course_and_enrollment(course_location)

        self.client.login(username=self.student.username, password=self.PASSWORD)
        response = self.client.get(reverse("dashboard"))

        courses_enrollments = list(get_course_enrollments(self.student, None, []))
        courses_enrollments.sort(key=lambda x: x.created, reverse=True)
        self.assertEqual(len(courses_enrollments), 3)

        recent_course_enrollments = _get_recently_enrolled_courses(courses_enrollments)
        self.assertEqual(len(recent_course_enrollments), 2)

        self.assertContains(
            response,
            "Thank you for enrolling in:".format(course_name=self.course.display_name)
        )
        self.assertContains(
            response,
            ' and '.join(enrollment.course.display_name for enrollment in recent_course_enrollments)
        )

    def test_dashboard_escaped_rendering(self):
        """
        Tests that the dashboard renders the escaped recent enrollment messages appropriately.
        """
        self._configure_message_timeout(600)
        self.client.login(username=self.student.username, password=self.PASSWORD)

        # New Course
        course_location = locator.CourseLocator('TestOrg', 'TestCourse', 'TestRun')
        xss_content = "<script>alert('XSS')</script>"
        course = CourseFactory.create(
            org=course_location.org,
            number=course_location.course,
            run=course_location.run,
            display_name=xss_content
        )
        CourseEnrollment.enroll(self.student, course.id)

        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Thank you for enrolling in")

        # Check if response is escaped
        self.assert_no_xss(response, xss_content)

    @ddt.data(
        # Register as honor in any course modes with no payment option
        ([('audit', 0), ('honor', 0)], 'honor', True),
        ([('honor', 0)], 'honor', True),
        # Register as honor in any course modes which has payment option
        ([('honor', 10)], 'honor', False),  # This is a paid course
        ([('audit', 0), ('honor', 0), ('professional', 20)], 'honor', True),
        ([('audit', 0), ('honor', 0), ('verified', 20)], 'honor', True),
        ([('audit', 0), ('honor', 0), ('verified', 20), ('professional', 20)], 'honor', True),
        # Register as audit in any course modes with no payment option
        ([('audit', 0), ('honor', 0)], 'audit', True),
        ([('audit', 0)], 'audit', True),
        ([], 'audit', True),
        # Register as audit in any course modes which has no payment option
        ([('audit', 0), ('honor', 0), ('verified', 10)], 'audit', True),
        # Register as verified in any course modes which has payment option
        ([('professional', 20)], 'professional', False),
        ([('verified', 20)], 'verified', False),
        ([('professional', 20), ('verified', 20)], 'verified', False),
        ([('audit', 0), ('honor', 0), ('verified', 20)], 'verified', False)
    )
    @ddt.unpack
    def test_donate_button(self, course_modes, enrollment_mode, show_donate):
        # Enable the enrollment success message
        self._configure_message_timeout(10000)

        # Enable donations
        DonationConfiguration(enabled=True).save()

        # Create the course mode(s)
        for mode, min_price in course_modes:
            CourseModeFactory.create(mode_slug=mode, course_id=self.course.id, min_price=min_price)

        self.enrollment.mode = enrollment_mode
        self.enrollment.save()

        # Check that the donate button is or is not displayed
        self.client.login(username=self.student.username, password=self.PASSWORD)
        response = self.client.get(reverse("dashboard"))

        if show_donate:
            self.assertContains(response, "donate-container")
        else:
            self.assertNotContains(response, "donate-container")

    def test_donate_button_honor_with_price(self):
        # Enable the enrollment success message and donations
        self._configure_message_timeout(10000)
        DonationConfiguration(enabled=True).save()

        # Create a white-label course mode
        # (honor mode with a price set)
        CourseModeFactory.create(mode_slug="honor", course_id=self.course.id, min_price=100)

        # Check that the donate button is NOT displayed
        self.client.login(username=self.student.username, password=self.PASSWORD)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "donate-container")

    @ddt.data(
        (True, False,),
        (True, True,),
        (False, False,),
        (False, True,),
    )
    @ddt.unpack
    def test_donate_button_with_enabled_site_configuration(self, enable_donation_config, enable_donation_site_config):
        # Enable the enrollment success message and donations
        self._configure_message_timeout(10000)

        # DonationConfiguration has low precedence if 'ENABLE_DONATIONS' is enable in SiteConfiguration
        DonationConfiguration(enabled=enable_donation_config).save()

        CourseModeFactory.create(mode_slug="audit", course_id=self.course.id, min_price=0)
        self.enrollment.mode = "audit"
        self.enrollment.save()
        self.client.login(username=self.student.username, password=self.PASSWORD)

        with with_site_configuration_context(configuration={'ENABLE_DONATIONS': enable_donation_site_config}):
            response = self.client.get(reverse("dashboard"))
            if enable_donation_site_config:
                self.assertContains(response, "donate-container")
            else:
                self.assertNotContains(response, "donate-container")
