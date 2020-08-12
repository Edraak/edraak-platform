# -*- coding: utf-8 -*-
"""
End-to-end tests for the LMS.
"""

import json
from datetime import datetime, timedelta

import ddt

from openedx.core.lib.tests import attr

from ...fixtures.course import CourseFixture, XBlockFixtureDesc
from ...pages.common.auto_auth import AutoAuthPage
from ...pages.common.logout import LogoutPage
from ...pages.lms.course_home import CourseHomePage
from ...pages.lms.courseware import CoursewarePage, CoursewareSequentialTabPage
from ...pages.lms.create_mode import ModeCreationPage
from ...pages.lms.dashboard import DashboardPage
from ...pages.lms.pay_and_verify import FakePaymentPage, FakeSoftwareSecureVerificationPage, PaymentAndVerificationFlow
from ...pages.lms.problem import ProblemPage
from ...pages.lms.progress import ProgressPage
from ...pages.lms.track_selection import TrackSelectionPage
from ...pages.studio.overview import CourseOutlinePage as StudioCourseOutlinePage
from ..helpers import EventsTestMixin, UniqueCourseTest, auto_auth, create_multiple_choice_problem


@attr(shard=9)
class CoursewareTest(UniqueCourseTest):
    """
    Test courseware.
    """
    USERNAME = "STUDENT_TESTER"
    EMAIL = "student101@example.com"

    def setUp(self):
        super(CoursewareTest, self).setUp()

        self.courseware_page = CoursewarePage(self.browser, self.course_id)
        self.course_home_page = CourseHomePage(self.browser, self.course_id)

        self.studio_course_outline = StudioCourseOutlinePage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

        # Install a course with sections/problems, tabs, updates, and handouts
        self.course_fix = CourseFixture(
            self.course_info['org'], self.course_info['number'],
            self.course_info['run'], self.course_info['display_name']
        )

        self.course_fix.add_children(
            XBlockFixtureDesc('chapter', 'Test Section 1').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 1').add_children(
                    XBlockFixtureDesc('problem', 'Test Problem 1')
                )
            ),
            XBlockFixtureDesc('chapter', 'Test Section 2').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 2').add_children(
                    XBlockFixtureDesc('problem', 'Test Problem 2')
                )
            )
        ).install()

        # Auto-auth register for the course.
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)

    def _goto_problem_page(self):
        """
        Open problem page with assertion.
        """
        self.courseware_page.visit()
        self.problem_page = ProblemPage(self.browser)  # pylint: disable=attribute-defined-outside-init
        self.assertEqual(self.problem_page.problem_name, 'Test Problem 1')

    def test_courseware(self):
        """
        Test courseware if recent visited subsection become unpublished.
        """

        # Visit problem page as a student.
        self._goto_problem_page()

        # Logout and login as a staff user.
        LogoutPage(self.browser).visit()
        auto_auth(self.browser, "STAFF_TESTER", "staff101@example.com", True, self.course_id)

        # Visit course outline page in studio.
        self.studio_course_outline.visit()

        # Set release date for subsection in future.
        self.studio_course_outline.change_problem_release_date()

        # Logout and login as a student.
        LogoutPage(self.browser).visit()
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)

        # Visit courseware as a student.
        self.courseware_page.visit()
        # Problem name should be "Test Problem 2".
        self.assertEqual(self.problem_page.problem_name, 'Test Problem 2')

    def test_course_tree_breadcrumb(self):
        """
        Scenario: Correct course tree breadcrumb is shown.

        Given that I am a registered user
        And I visit my courseware page
        Then I should see correct course tree breadcrumb
        """
        xblocks = self.course_fix.get_nested_xblocks(category="problem")
        for index in range(1, len(xblocks) + 1):
            test_section_title = 'Test Section {}'.format(index)
            test_subsection_title = 'Test Subsection {}'.format(index)
            test_unit_title = 'Test Problem {}'.format(index)
            self.course_home_page.visit()
            self.course_home_page.outline.go_to_section(test_section_title, test_subsection_title)
            course_nav = self.courseware_page.nav
            self.assertEqual(course_nav.breadcrumb_section_title, test_section_title)
            self.assertEqual(course_nav.breadcrumb_subsection_title, test_subsection_title)
            self.assertEqual(course_nav.breadcrumb_unit_title, test_unit_title)


@attr(shard=9)
@ddt.ddt
class ProctoredExamTest(UniqueCourseTest):
    """
    Tests for proctored exams.
    """
    USERNAME = "STUDENT_TESTER"
    EMAIL = "student101@example.com"

    def setUp(self):
        super(ProctoredExamTest, self).setUp()

        self.courseware_page = CoursewarePage(self.browser, self.course_id)

        self.studio_course_outline = StudioCourseOutlinePage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

        # Install a course with sections/problems, tabs, updates, and handouts
        course_fix = CourseFixture(
            self.course_info['org'], self.course_info['number'],
            self.course_info['run'], self.course_info['display_name']
        )
        course_fix.add_advanced_settings({
            "enable_proctored_exams": {"value": "true"}
        })

        course_fix.add_children(
            XBlockFixtureDesc('chapter', 'Test Section 1').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 1').add_children(
                    XBlockFixtureDesc('problem', 'Test Problem 1')
                )
            )
        ).install()

        self.track_selection_page = TrackSelectionPage(self.browser, self.course_id)
        self.payment_and_verification_flow = PaymentAndVerificationFlow(self.browser, self.course_id)
        self.immediate_verification_page = PaymentAndVerificationFlow(
            self.browser, self.course_id, entry_point='verify-now'
        )
        self.upgrade_page = PaymentAndVerificationFlow(self.browser, self.course_id, entry_point='upgrade')
        self.fake_payment_page = FakePaymentPage(self.browser, self.course_id)
        self.dashboard_page = DashboardPage(self.browser)
        self.problem_page = ProblemPage(self.browser)

        # Add a verified mode to the course
        ModeCreationPage(
            self.browser, self.course_id, mode_slug=u'verified', mode_display_name=u'Verified Certificate',
            min_price=10, suggested_prices='10,20'
        ).visit()

        # Auto-auth register for the course.
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)

    def _login_as_a_verified_user(self):
        """
        login as a verififed user
        """

        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)

        # the track selection page cannot be visited. see the other tests to see if any prereq is there.
        # Navigate to the track selection page
        self.track_selection_page.visit()

        # Enter the payment and verification flow by choosing to enroll as verified
        self.track_selection_page.enroll('verified')

        # Proceed to the fake payment page
        self.payment_and_verification_flow.proceed_to_payment()

        # Submit payment
        self.fake_payment_page.submit_payment()

    def _verify_user(self):
        """
        Takes user through the verification flow and then marks the verification as 'approved'.
        """
        # Immediately verify the user
        self.immediate_verification_page.immediate_verification()

        # Take face photo and proceed to the ID photo step
        self.payment_and_verification_flow.webcam_capture()
        self.payment_and_verification_flow.next_verification_step(self.immediate_verification_page)

        # Take ID photo and proceed to the review photos step
        self.payment_and_verification_flow.webcam_capture()
        self.payment_and_verification_flow.next_verification_step(self.immediate_verification_page)

        # Submit photos and proceed to the enrollment confirmation step
        self.payment_and_verification_flow.next_verification_step(self.immediate_verification_page)

        # Mark the verification as passing.
        verification = FakeSoftwareSecureVerificationPage(self.browser).visit()
        verification.mark_approved()

    def test_can_create_proctored_exam_in_studio(self):
        """
        Given that I am a staff member
        When I visit the course outline page in studio.
        And open the subsection edit dialog
        Then I can view all settings related to Proctored and timed exams
        """
        LogoutPage(self.browser).visit()
        auto_auth(self.browser, "STAFF_TESTER", "staff101@example.com", True, self.course_id)
        self.studio_course_outline.visit()

        self.studio_course_outline.open_subsection_settings_dialog()
        self.assertTrue(self.studio_course_outline.proctoring_items_are_displayed())

    def _setup_and_take_timed_exam(self, hide_after_due=False):
        """
        Helper to perform the common action "set up a timed exam as staff,
        then take it as student"
        """
        LogoutPage(self.browser).visit()
        auto_auth(self.browser, "STAFF_TESTER", "staff101@example.com", True, self.course_id)
        self.studio_course_outline.visit()
        self.studio_course_outline.open_subsection_settings_dialog()

        self.studio_course_outline.select_advanced_tab()
        self.studio_course_outline.make_exam_timed(hide_after_due=hide_after_due)

        LogoutPage(self.browser).visit()
        self._login_as_a_verified_user()
        self.courseware_page.visit()

        self.courseware_page.start_timed_exam()
        self.assertTrue(self.courseware_page.is_timer_bar_present)

        self.courseware_page.stop_timed_exam()
        self.courseware_page.wait_for_page()
        self.assertTrue(self.courseware_page.has_submitted_exam_message())

        LogoutPage(self.browser).visit()

    @ddt.data(True, False)
    def test_timed_exam_flow(self, hide_after_due):
        """
        Given that I am a staff member on the exam settings section
        select advanced settings tab
        When I Make the exam timed.
        And I login as a verified student.
        And visit the courseware as a verified student.
        And I start the timed exam
        Then I am taken to the exam with a timer bar showing
        When I finish the exam
        Then I see the exam submitted dialog in place of the exam
        When I log back into studio as a staff member
        And change the problem's due date to be in the past
        And log back in as the original verified student
        Then I see the exam or message in accordance with the hide_after_due setting
        """
        self._setup_and_take_timed_exam(hide_after_due)

        LogoutPage(self.browser).visit()
        auto_auth(self.browser, "STAFF_TESTER", "staff101@example.com", True, self.course_id)
        self.studio_course_outline.visit()
        last_week = (datetime.today() - timedelta(days=7)).strftime("%m/%d/%Y")
        self.studio_course_outline.change_problem_due_date(last_week)

        LogoutPage(self.browser).visit()
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)
        self.courseware_page.visit()
        self.assertEqual(self.courseware_page.has_submitted_exam_message(), hide_after_due)

    def test_field_visiblity_with_all_exam_types(self):
        """
        Given that I am a staff member
        And I have visited the course outline page in studio.
        And the subsection edit dialog is open
        select advanced settings tab
        For each of None, Timed, Proctored, and Practice exam types
        The time allotted and review rules fields have proper visibility
        None: False, False
        Timed: True, False
        Proctored: True, True
        Practice: True, False
        """
        LogoutPage(self.browser).visit()
        auto_auth(self.browser, "STAFF_TESTER", "staff101@example.com", True, self.course_id)
        self.studio_course_outline.visit()

        self.studio_course_outline.open_subsection_settings_dialog()
        self.studio_course_outline.select_advanced_tab()

        self.studio_course_outline.select_none_exam()
        self.assertFalse(self.studio_course_outline.time_allotted_field_visible())
        self.assertFalse(self.studio_course_outline.exam_review_rules_field_visible())

        self.studio_course_outline.select_timed_exam()
        self.assertTrue(self.studio_course_outline.time_allotted_field_visible())
        self.assertFalse(self.studio_course_outline.exam_review_rules_field_visible())

        self.studio_course_outline.select_proctored_exam()
        self.assertTrue(self.studio_course_outline.time_allotted_field_visible())
        self.assertTrue(self.studio_course_outline.exam_review_rules_field_visible())

        self.studio_course_outline.select_practice_exam()
        self.assertTrue(self.studio_course_outline.time_allotted_field_visible())
        self.assertFalse(self.studio_course_outline.exam_review_rules_field_visible())


class CoursewareMultipleVerticalsTestBase(UniqueCourseTest, EventsTestMixin):
    """
    Base class with setup for testing courseware with multiple verticals
    """
    USERNAME = "STUDENT_TESTER"
    EMAIL = "student101@example.com"

    def setUp(self):
        super(CoursewareMultipleVerticalsTestBase, self).setUp()

        self.courseware_page = CoursewarePage(self.browser, self.course_id)
        self.course_home_page = CourseHomePage(self.browser, self.course_id)

        self.studio_course_outline = StudioCourseOutlinePage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

        # Install a course with sections/problems, tabs, updates, and handouts
        course_fix = CourseFixture(
            self.course_info['org'], self.course_info['number'],
            self.course_info['run'], self.course_info['display_name']
        )

        course_fix.add_children(
            XBlockFixtureDesc('chapter', 'Test Section 1').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 1,1').add_children(
                    XBlockFixtureDesc('problem', 'Test Problem 1', data='<problem>problem 1 dummy body</problem>'),
                    XBlockFixtureDesc('html', 'html 1', data="<html>html 1 dummy body</html>"),
                    XBlockFixtureDesc('problem', 'Test Problem 2', data="<problem>problem 2 dummy body</problem>"),
                    XBlockFixtureDesc('html', 'html 2', data="<html>html 2 dummy body</html>"),
                ),
                XBlockFixtureDesc('sequential', 'Test Subsection 1,2').add_children(
                    XBlockFixtureDesc('problem', 'Test Problem 3', data='<problem>problem 3 dummy body</problem>'),
                ),
                XBlockFixtureDesc(
                    'sequential', 'Test HIDDEN Subsection', metadata={'visible_to_staff_only': True}
                ).add_children(
                    XBlockFixtureDesc('problem', 'Test HIDDEN Problem', data='<problem>hidden problem</problem>'),
                ),
            ),
            XBlockFixtureDesc('chapter', 'Test Section 2').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 2,1').add_children(
                    XBlockFixtureDesc('problem', 'Test Problem 4', data='<problem>problem 4 dummy body</problem>'),
                ),
            ),
            XBlockFixtureDesc('chapter', 'Test HIDDEN Section', metadata={'visible_to_staff_only': True}).add_children(
                XBlockFixtureDesc('sequential', 'Test HIDDEN Subsection'),
            ),
        ).install()

        # Auto-auth register for the course.
        AutoAuthPage(self.browser, username=self.USERNAME, email=self.EMAIL,
                     course_id=self.course_id, staff=False).visit()


@attr(shard=9)
class CoursewareMultipleVerticalsTest(CoursewareMultipleVerticalsTestBase):
    """
    Test courseware with multiple verticals
    """

    def test_navigation_buttons(self):
        self.courseware_page.visit()

        # start in first section
        self.assert_navigation_state('Test Section 1', 'Test Subsection 1,1', 0, next_enabled=True, prev_enabled=False)

        # next takes us to next tab in sequential
        self.courseware_page.click_next_button_on_top()
        self.assert_navigation_state('Test Section 1', 'Test Subsection 1,1', 1, next_enabled=True, prev_enabled=True)

        # go to last sequential position
        self.courseware_page.go_to_sequential_position(4)
        self.assert_navigation_state('Test Section 1', 'Test Subsection 1,1', 3, next_enabled=True, prev_enabled=True)

        # next takes us to next sequential
        self.courseware_page.click_next_button_on_bottom()
        self.assert_navigation_state('Test Section 1', 'Test Subsection 1,2', 0, next_enabled=True, prev_enabled=True)

        # next takes us to next chapter
        self.courseware_page.click_next_button_on_top()
        self.assert_navigation_state('Test Section 2', 'Test Subsection 2,1', 0, next_enabled=False, prev_enabled=True)

        # previous takes us to previous chapter
        self.courseware_page.click_previous_button_on_top()
        self.assert_navigation_state('Test Section 1', 'Test Subsection 1,2', 0, next_enabled=True, prev_enabled=True)

        # previous takes us to last tab in previous sequential
        self.courseware_page.click_previous_button_on_bottom()
        self.assert_navigation_state('Test Section 1', 'Test Subsection 1,1', 3, next_enabled=True, prev_enabled=True)

        # previous takes us to previous tab in sequential
        self.courseware_page.click_previous_button_on_bottom()
        self.assert_navigation_state('Test Section 1', 'Test Subsection 1,1', 2, next_enabled=True, prev_enabled=True)

        # test UI events emitted by navigation
        filter_sequence_ui_event = lambda event: event.get('name', '').startswith('edx.ui.lms.sequence.')

        sequence_ui_events = self.wait_for_events(event_filter=filter_sequence_ui_event, timeout=2)
        legacy_events = [ev for ev in sequence_ui_events if ev['event_type'] in {'seq_next', 'seq_prev', 'seq_goto'}]
        nonlegacy_events = [ev for ev in sequence_ui_events if ev not in legacy_events]

        self.assertTrue(all('old' in json.loads(ev['event']) for ev in legacy_events))
        self.assertTrue(all('new' in json.loads(ev['event']) for ev in legacy_events))
        self.assertFalse(any('old' in json.loads(ev['event']) for ev in nonlegacy_events))
        self.assertFalse(any('new' in json.loads(ev['event']) for ev in nonlegacy_events))

        self.assert_events_match(
            [
                {
                    'event_type': 'seq_next',
                    'event': {
                        'old': 1,
                        'new': 2,
                        'current_tab': 1,
                        'tab_count': 4,
                        'widget_placement': 'top',
                    }
                },
                {
                    'event_type': 'seq_goto',
                    'event': {
                        'old': 2,
                        'new': 4,
                        'current_tab': 2,
                        'target_tab': 4,
                        'tab_count': 4,
                        'widget_placement': 'top',
                    }
                },
                {
                    'event_type': 'edx.ui.lms.sequence.next_selected',
                    'event': {
                        'current_tab': 4,
                        'tab_count': 4,
                        'widget_placement': 'bottom',
                    }
                },
                {
                    'event_type': 'edx.ui.lms.sequence.next_selected',
                    'event': {
                        'current_tab': 1,
                        'tab_count': 1,
                        'widget_placement': 'top',
                    }
                },
                {
                    'event_type': 'edx.ui.lms.sequence.previous_selected',
                    'event': {
                        'current_tab': 1,
                        'tab_count': 1,
                        'widget_placement': 'top',
                    }
                },
                {
                    'event_type': 'edx.ui.lms.sequence.previous_selected',
                    'event': {
                        'current_tab': 1,
                        'tab_count': 1,
                        'widget_placement': 'bottom',
                    }
                },
                {
                    'event_type': 'seq_prev',
                    'event': {
                        'old': 4,
                        'new': 3,
                        'current_tab': 4,
                        'tab_count': 4,
                        'widget_placement': 'bottom',
                    }
                },
            ],
            sequence_ui_events
        )

    def assert_navigation_state(
            self, section_title, subsection_title, subsection_position, next_enabled, prev_enabled
    ):
        """
        Verifies that the navigation state is as expected.
        """
        self.assertTrue(self.courseware_page.nav.is_on_section(section_title, subsection_title))
        self.assertEquals(self.courseware_page.sequential_position, subsection_position)
        self.assertEquals(self.courseware_page.is_next_button_enabled, next_enabled)
        self.assertEquals(self.courseware_page.is_previous_button_enabled, prev_enabled)

    def test_tab_position(self):
        # test that using the position in the url direct to correct tab in courseware
        self.course_home_page.visit()

        self.course_home_page.outline.go_to_section('Test Section 1', 'Test Subsection 1,1')
        subsection_url = self.browser.current_url
        url_part_list = subsection_url.split('/')

        course_id = url_part_list[-5]
        chapter_id = url_part_list[-3]
        subsection_id = url_part_list[-2]
        problem1_page = CoursewareSequentialTabPage(
            self.browser,
            course_id=course_id,
            chapter=chapter_id,
            subsection=subsection_id,
            position=1
        ).visit()
        self.assertIn('problem 1 dummy body', problem1_page.get_selected_tab_content())

        html1_page = CoursewareSequentialTabPage(
            self.browser,
            course_id=course_id,
            chapter=chapter_id,
            subsection=subsection_id,
            position=2
        ).visit()
        self.assertIn('html 1 dummy body', html1_page.get_selected_tab_content())

        problem2_page = CoursewareSequentialTabPage(
            self.browser,
            course_id=course_id,
            chapter=chapter_id,
            subsection=subsection_id,
            position=3
        ).visit()
        self.assertIn('problem 2 dummy body', problem2_page.get_selected_tab_content())

        html2_page = CoursewareSequentialTabPage(
            self.browser,
            course_id=course_id,
            chapter=chapter_id,
            subsection=subsection_id,
            position=4
        ).visit()
        self.assertIn('html 2 dummy body', html2_page.get_selected_tab_content())


@attr(shard=9)
class ProblemStateOnNavigationTest(UniqueCourseTest):
    """
    Test courseware with problems in multiple verticals.
    """
    USERNAME = "STUDENT_TESTER"
    EMAIL = "student101@example.com"

    problem1_name = 'MULTIPLE CHOICE TEST PROBLEM 1'
    problem2_name = 'MULTIPLE CHOICE TEST PROBLEM 2'

    def setUp(self):
        super(ProblemStateOnNavigationTest, self).setUp()

        self.courseware_page = CoursewarePage(self.browser, self.course_id)

        # Install a course with section, tabs and multiple choice problems.
        course_fix = CourseFixture(
            self.course_info['org'], self.course_info['number'],
            self.course_info['run'], self.course_info['display_name']
        )

        course_fix.add_children(
            XBlockFixtureDesc('chapter', 'Test Section 1').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 1,1').add_children(
                    create_multiple_choice_problem(self.problem1_name),
                    create_multiple_choice_problem(self.problem2_name),
                ),
            ),
        ).install()

        # Auto-auth register for the course.
        AutoAuthPage(
            self.browser, username=self.USERNAME, email=self.EMAIL,
            course_id=self.course_id, staff=False
        ).visit()

        self.courseware_page.visit()
        self.problem_page = ProblemPage(self.browser)

    def go_to_tab_and_assert_problem(self, position, problem_name):
        """
        Go to sequential tab and assert that we are on problem whose name is given as a parameter.
        Args:
            position: Position of the sequential tab
            problem_name: Name of the problem
        """
        self.courseware_page.go_to_sequential_position(position)
        self.problem_page.wait_for_element_presence(
            self.problem_page.CSS_PROBLEM_HEADER,
            'wait for problem header'
        )
        self.assertEqual(self.problem_page.problem_name, problem_name)

    def test_perform_problem_submit_and_navigate(self):
        """
        Scenario:
        I go to sequential position 1
        Facing problem1, I select 'choice_1'
        Then I click submit button
        Then I go to sequential position 2
        Then I came back to sequential position 1 again
        Facing problem1, I observe the problem1 content is not
        outdated before and after sequence navigation
        """
        # Go to sequential position 1 and assert that we are on problem 1.
        self.go_to_tab_and_assert_problem(1, self.problem1_name)

        # Update problem 1's content state by clicking check button.
        self.problem_page.click_choice('choice_choice_1')
        self.problem_page.click_submit()
        self.problem_page.wait_for_expected_status('label.choicegroup_incorrect', 'incorrect')

        # Save problem 1's content state as we're about to switch units in the sequence.
        problem1_content_before_switch = self.problem_page.problem_content
        before_meta = self.problem_page.problem_meta

        # Go to sequential position 2 and assert that we are on problem 2.
        self.go_to_tab_and_assert_problem(2, self.problem2_name)

        # Come back to our original unit in the sequence and assert that the content hasn't changed.
        self.go_to_tab_and_assert_problem(1, self.problem1_name)
        problem1_content_after_coming_back = self.problem_page.problem_content
        after_meta = self.problem_page.problem_meta

        self.assertEqual(problem1_content_before_switch, problem1_content_after_coming_back)
        self.assertEqual(before_meta, after_meta)

    def test_perform_problem_save_and_navigate(self):
        """
        Scenario:
        I go to sequential position 1
        Facing problem1, I select 'choice_1'
        Then I click save button
        Then I go to sequential position 2
        Then I came back to sequential position 1 again
        Facing problem1, I observe the problem1 content is not
        outdated before and after sequence navigation
        """
        # Go to sequential position 1 and assert that we are on problem 1.
        self.go_to_tab_and_assert_problem(1, self.problem1_name)

        # Update problem 1's content state by clicking save button.
        self.problem_page.click_choice('choice_choice_1')
        self.problem_page.click_save()
        self.problem_page.wait_for_save_notification()

        # Save problem 1's content state as we're about to switch units in the sequence.
        problem1_content_before_switch = self.problem_page.problem_input_content
        before_meta = self.problem_page.problem_meta

        # Go to sequential position 2 and assert that we are on problem 2.
        self.go_to_tab_and_assert_problem(2, self.problem2_name)

        self.problem_page.wait_for_expected_status('span.unanswered', 'unanswered')

        # Come back to our original unit in the sequence and assert that the content hasn't changed.
        self.go_to_tab_and_assert_problem(1, self.problem1_name)
        problem1_content_after_coming_back = self.problem_page.problem_input_content
        after_meta = self.problem_page.problem_meta

        self.assertIn(problem1_content_after_coming_back, problem1_content_before_switch)
        self.assertEqual(before_meta, after_meta)


@attr(shard=9)
class SubsectionHiddenAfterDueDateTest(UniqueCourseTest):
    """
    Tests the "hide after due date" setting for
    subsections.
    """
    USERNAME = "STUDENT_TESTER"
    EMAIL = "student101@example.com"

    def setUp(self):
        super(SubsectionHiddenAfterDueDateTest, self).setUp()

        self.courseware_page = CoursewarePage(self.browser, self.course_id)
        self.logout_page = LogoutPage(self.browser)

        self.studio_course_outline = StudioCourseOutlinePage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

        # Install a course with sections/problems, tabs, updates, and handouts
        course_fix = CourseFixture(
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run'],
            self.course_info['display_name']
        )

        course_fix.add_children(
            XBlockFixtureDesc('chapter', 'Test Section 1').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 1').add_children(
                    create_multiple_choice_problem('Test Problem 1')
                )
            )
        ).install()

        self.progress_page = ProgressPage(self.browser, self.course_id)
        self._setup_subsection()

        # Auto-auth register for the course.
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)

    def _setup_subsection(self):
        """
        Helper to set up a problem subsection as staff, then take
        it as a student.
        """
        self.logout_page.visit()
        auto_auth(self.browser, "STAFF_TESTER", "staff101@example.com", True, self.course_id)
        self.studio_course_outline.visit()
        self.studio_course_outline.open_subsection_settings_dialog()

        self.studio_course_outline.select_visibility_tab()
        self.studio_course_outline.make_subsection_hidden_after_due_date()

        self.logout_page.visit()
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)
        self.courseware_page.visit()

        self.logout_page.visit()

    def test_subsecton_hidden_after_due_date(self):
        """
        Given that I am a staff member on the subsection settings section
        And I select the advanced settings tab
        When I Make the subsection hidden after its due date.
        And I login as a student.
        And visit the subsection in the courseware as a verified student.
        Then I am able to see the subsection
        And when I visit the progress page
        Then I should be able to see my grade on the progress page
        When I log in as staff
        And I make the subsection due in the past so that the current date is past its due date
        And I log in as a student
        And I visit the subsection in the courseware
        Then the subsection should be hidden with a message that its due date has passed
        And when I visit the progress page
        Then I should be able to see my grade on the progress page
        """
        self.logout_page.visit()
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)
        self.courseware_page.visit()
        self.assertFalse(self.courseware_page.content_hidden_past_due_date())

        self.progress_page.visit()
        self.assertEqual(self.progress_page.scores('Test Section 1', 'Test Subsection 1'), [(0, 1)])

        self.logout_page.visit()
        auto_auth(self.browser, "STAFF_TESTER", "staff101@example.com", True, self.course_id)
        self.studio_course_outline.visit()
        last_week = (datetime.today() - timedelta(days=7)).strftime("%m/%d/%Y")
        self.studio_course_outline.change_problem_due_date(last_week)

        self.logout_page.visit()
        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)
        self.courseware_page.visit()
        self.assertTrue(self.courseware_page.content_hidden_past_due_date())

        self.progress_page.visit()
        self.assertEqual(self.progress_page.scores('Test Section 1', 'Test Subsection 1'), [(0, 1)])


@attr(shard=9)
class CompletionTestCase(UniqueCourseTest, EventsTestMixin):
    """
    Test the completion on view functionality.
    """
    USERNAME = "STUDENT_TESTER"
    EMAIL = "student101@example.com"
    COMPLETION_BY_VIEWING_DELAY_MS = '1000'

    def setUp(self):
        super(CompletionTestCase, self).setUp()

        self.studio_course_outline = StudioCourseOutlinePage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

        # Install a course with sections/problems, tabs, updates, and handouts
        course_fix = CourseFixture(
            self.course_info['org'], self.course_info['number'],
            self.course_info['run'], self.course_info['display_name']
        )

        self.html_1_block = XBlockFixtureDesc('html', 'html 1', data="<html>html 1 dummy body</html>")
        self.problem_1_block = XBlockFixtureDesc(
            'problem', 'Test Problem 1', data='<problem>problem 1 dummy body</problem>'
        )

        course_fix.add_children(
            XBlockFixtureDesc('chapter', 'Test Section 1').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 1,1').add_children(
                    XBlockFixtureDesc('vertical', 'Test Unit 1,1,1').add_children(
                        XBlockFixtureDesc('html', 'html 1', data="<html>html 1 dummy body</html>"),
                        XBlockFixtureDesc(
                            'html', 'html 2',
                            data=("<html>html 2 dummy body</html>" * 100) + "<span id='html2-end'>End</span>",
                        ),
                        XBlockFixtureDesc('problem', 'Test Problem 1', data='<problem>problem 1 dummy body</problem>'),
                    ),
                    XBlockFixtureDesc('vertical', 'Test Unit 1,1,2').add_children(
                        XBlockFixtureDesc('html', 'html 1', data="<html>html 1 dummy body</html>"),
                        XBlockFixtureDesc('problem', 'Test Problem 1', data='<problem>problem 1 dummy body</problem>'),
                    ),
                    XBlockFixtureDesc('vertical', 'Test Unit 1,1,2').add_children(
                        self.html_1_block,
                        self.problem_1_block,
                    ),
                ),
            ),
        ).install()

        # Auto-auth register for the course.
        AutoAuthPage(self.browser, username=self.USERNAME, email=self.EMAIL,
                     course_id=self.course_id, staff=False).visit()


@attr(shard=9)
class WordCloudTests(UniqueCourseTest):
    """
    Tests the Word Cloud.
    """
    USERNAME = "STUDENT_TESTER"
    EMAIL = "student101@example.com"

    def setUp(self):
        super(WordCloudTests, self).setUp()

        self.courseware_page = CoursewarePage(self.browser, self.course_id)

        self.studio_course_outline = StudioCourseOutlinePage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

        # Install a course
        course_fix = CourseFixture(
            self.course_info['org'], self.course_info['number'],
            self.course_info['run'], self.course_info['display_name']
        )
        # Set word cloud value against advanced modules in advanced settings
        course_fix.add_advanced_settings({
            "advanced_modules": {"value": ["word_cloud"]},
        })

        course_fix.add_children(
            XBlockFixtureDesc('chapter', 'Test Section 1').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 1').add_children(
                    XBlockFixtureDesc('vertical', 'Test Unit').add_children(
                        XBlockFixtureDesc(
                            'word_cloud', 'advanced WORDCLOUD'
                        )
                    )
                )
            )
        ).install()

        auto_auth(self.browser, self.USERNAME, self.EMAIL, False, self.course_id)
        self.courseware_page.visit()

    def test_word_cloud_is_rendered_with_empty_result(self):
        """
        Scenario: Word Cloud component in LMS is rendered with empty result
        Given the course has a Word Cloud component
            Then I view the word cloud and it has rendered
        When I press the Save button
            Then I see the empty result
        """
        self.assertTrue(self.courseware_page.is_word_cloud_rendered)
        self.courseware_page.save_word_cloud()
        self.assertEqual(self.courseware_page.word_cloud_answer_list, '')

    def test_word_cloud_is_rendered_with_result(self):
        """
        Scenario: Word Cloud component in LMS is rendered with result
        Given the course has a Word Cloud component
            Then I view the word cloud and it has rendered
        When I fill inputs
        And I press the Save button
            Then I see the result with words count
        """
        expected_data = ['test_wordcloud1', 'test_wordcloud2', 'test_wordcloud3', 'test_wordcloud4', 'test_wordcloud5']
        self.assertTrue(self.courseware_page.is_word_cloud_rendered)
        self.courseware_page.input_word_cloud('test_wordcloud')
        self.courseware_page.save_word_cloud()
        self.assertItemsEqual(expected_data, self.courseware_page.word_cloud_answer_list)
