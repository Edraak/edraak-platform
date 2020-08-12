# -*- coding: utf-8 -*-
"""
Bok choy acceptance tests for problems in the LMS

See also old lettuce tests in lms/djangoapps/courseware/features/problems.feature
"""
from textwrap import dedent
from unittest import skip
import time
import ddt

from common.test.acceptance.fixtures.course import CourseFixture, XBlockFixtureDesc
from common.test.acceptance.pages.common.auto_auth import AutoAuthPage
from common.test.acceptance.pages.lms.courseware import CoursewarePage
from common.test.acceptance.pages.lms.login_and_register import CombinedLoginAndRegisterPage
from common.test.acceptance.pages.lms.problem import ProblemPage
from common.test.acceptance.tests.helpers import EventsTestMixin, UniqueCourseTest
from openedx.core.lib.tests import attr


class ProblemsTest(UniqueCourseTest):
    """
    Base class for tests of problems in the LMS.
    """

    def setUp(self):
        super(ProblemsTest, self).setUp()

        self.username = "test_student_{uuid}".format(uuid=self.unique_id[0:8])
        self.email = "{username}@example.com".format(username=self.username)
        self.password = "keep it secret; keep it safe."

        self.xqueue_grade_response = None

        self.courseware_page = CoursewarePage(self.browser, self.course_id)

        # Install a course with a hierarchy and problems
        course_fixture = CourseFixture(
            self.course_info['org'], self.course_info['number'],
            self.course_info['run'], self.course_info['display_name']
        )

        problem = self.get_problem()
        sequential = self.get_sequential()
        course_fixture.add_children(
            XBlockFixtureDesc('chapter', 'Test Section').add_children(
                sequential.add_children(problem)
            )
        ).install()

        # Auto-auth register for the course.
        AutoAuthPage(
            self.browser,
            username=self.username,
            email=self.email,
            password=self.password,
            course_id=self.course_id,
            staff=True
        ).visit()

    def get_problem(self):
        """ Subclasses should override this to complete the fixture """
        raise NotImplementedError()

    def get_sequential(self):
        """ Subclasses can override this to add a sequential with metadata """
        return XBlockFixtureDesc('sequential', 'Test Subsection')


@attr(shard=9)
class ProblemClarificationTest(ProblemsTest):
    """
    Tests the <clarification> element that can be used in problem XML.
    """

    def get_problem(self):
        """
        Create a problem with a <clarification>
        """
        xml = dedent("""
            <problem markdown="null">
                <text>
                    <p>
                        Given the data in Table 7 <clarification>Table 7: "Example PV Installation Costs",
                        Page 171 of Roberts textbook</clarification>, compute the ROI
                        <clarification>Return on Investment <strong>(per year)</strong></clarification> over 20 years.
                    </p>
                    <numericalresponse answer="6.5">
                        <label>Enter the annual ROI</label>
                        <textline trailing_text="%" />
                    </numericalresponse>
                </text>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TOOLTIP TEST PROBLEM', data=xml)

    def test_clarification(self):
        """
        Test that we can see the <clarification> tooltips.
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        self.assertEqual(problem_page.problem_name, 'TOOLTIP TEST PROBLEM')
        problem_page.click_clarification(0)
        self.assertIn('"Example PV Installation Costs"', problem_page.visible_tooltip_text)
        problem_page.click_clarification(1)
        tooltip_text = problem_page.visible_tooltip_text
        self.assertIn('Return on Investment', tooltip_text)
        self.assertIn('per year', tooltip_text)
        self.assertNotIn('strong', tooltip_text)


@attr(shard=9)
class ProblemHintTest(ProblemsTest, EventsTestMixin):
    """
    Base test class for problem hint tests.
    """
    def verify_check_hint(self, answer, answer_text, expected_events):
        """
        Verify clicking Check shows the extended hint in the problem message.
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        self.assertEqual(problem_page.problem_text[0], u'question text')
        problem_page.fill_answer(answer)
        problem_page.click_submit()
        self.assertEqual(problem_page.message_text, answer_text)
        # Check for corresponding tracking event
        actual_events = self.wait_for_events(
            event_filter={'event_type': 'edx.problem.hint.feedback_displayed'},
            number_of_matches=1
        )
        self.assert_events_match(expected_events, actual_events)

    def verify_demand_hints(self, first_hint, second_hint, expected_events):
        """
        Test clicking through the demand hints and verify the events sent.
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)

        # The hint notification should not be visible on load
        self.assertFalse(problem_page.is_hint_notification_visible())

        # The two Hint button should be enabled. One visible, one present, but not visible in the DOM
        self.assertEqual([None, None], problem_page.get_hint_button_disabled_attr())

        # The hint button rotates through multiple hints
        problem_page.click_hint(hint_index=0)
        self.assertTrue(problem_page.is_hint_notification_visible())
        self.assertEqual(problem_page.hint_text, first_hint)
        # Now there are two "hint" buttons, as there is also one in the hint notification.
        self.assertEqual([None, None], problem_page.get_hint_button_disabled_attr())

        problem_page.click_hint(hint_index=1)
        self.assertEqual(problem_page.hint_text, second_hint)
        # Now both "hint" buttons should be disabled, as there are no more hints.
        self.assertEqual(['true', 'true'], problem_page.get_hint_button_disabled_attr())

        # Now click on "Review" and make sure the focus goes to the correct place.
        problem_page.click_review_in_notification(notification_type='hint')
        problem_page.wait_for_focus_on_problem_meta()

        # Check corresponding tracking events
        actual_events = self.wait_for_events(
            event_filter={'event_type': 'edx.problem.hint.demandhint_displayed'},
            number_of_matches=2
        )
        self.assert_events_match(expected_events, actual_events)

    def get_problem(self):
        """ Subclasses should override this to complete the fixture """
        raise NotImplementedError()


@attr(shard=9)
class ProblemNotificationTests(ProblemsTest):
    """
    Tests that the notifications are visible when expected.
    """

    def get_problem(self):
        """
        Problem structure.
        """
        xml = dedent("""
            <problem>
                <label>Which of the following countries has the largest population?</label>
                    <multiplechoiceresponse>
                      <choicegroup type="MultipleChoice">
                        <choice correct="false">Brazil <choicehint>timely feedback -- explain why an almost correct answer is wrong</choicehint></choice>
                        <choice correct="false">Germany</choice>
                        <choice correct="true">Indonesia</choice>
                        <choice correct="false">Russia</choice>
                      </choicegroup>
                    </multiplechoiceresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml,
                                 metadata={'max_attempts': 10},
                                 grader_type='Final Exam')

    def test_notification_updates(self):
        """
        Verifies that the notification is removed and not visible when it should be
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        problem_page.click_choice("choice_2")
        self.assertFalse(problem_page.is_success_notification_visible())
        problem_page.click_submit()
        problem_page.wait_success_notification()
        self.assertEqual('Question 1: correct', problem_page.status_sr_text)

        # Clicking Save should clear the submit notification
        problem_page.click_save()
        self.assertFalse(problem_page.is_success_notification_visible())
        problem_page.wait_for_save_notification()

        # Changing the answer should clear the save notification
        problem_page.click_choice("choice_1")
        self.assertFalse(problem_page.is_save_notification_visible())
        problem_page.click_save()
        problem_page.wait_for_save_notification()

        # Submitting the problem again should clear the save notification
        problem_page.click_submit()
        problem_page.wait_incorrect_notification()
        self.assertEqual('Question 1: incorrect', problem_page.status_sr_text)
        self.assertFalse(problem_page.is_save_notification_visible())


@attr(shard=9)
class ProblemFeedbackNotificationTests(ProblemsTest):
    """
    Tests that the feedback notifications are visible when expected.
    """

    def get_problem(self):
        """
        Problem structure.
        """
        xml = dedent("""
            <problem>
                <label>Which of the following countries has the largest population?</label>
                    <multiplechoiceresponse>
                      <choicegroup type="MultipleChoice">
                        <choice correct="false">Brazil <choicehint>timely feedback -- explain why an almost correct answer is wrong</choicehint></choice>
                        <choice correct="false">Germany</choice>
                        <choice correct="true">Indonesia</choice>
                        <choice correct="false">Russia</choice>
                      </choicegroup>
                    </multiplechoiceresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml,
                                 metadata={'max_attempts': 10},
                                 grader_type='Final Exam')

    def test_feedback_notification_hides_after_save(self):
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        problem_page.click_choice("choice_0")
        problem_page.click_submit()
        problem_page.wait_for_feedback_message_visibility()
        problem_page.click_choice("choice_1")
        problem_page.click_save()
        self.assertFalse(problem_page.is_feedback_message_notification_visible())


@attr(shard=9)
class ProblemSaveStatusUpdateTests(ProblemsTest):
    """
    Tests the problem status updates correctly with an answer change and save.
    """
    def get_problem(self):
        """
        Problem structure.
        """
        xml = dedent("""
            <problem>
                <label>Which of the following countries has the largest population?</label>
                    <multiplechoiceresponse>
                      <choicegroup type="MultipleChoice">
                        <choice correct="false">Brazil <choicehint>timely feedback -- explain why an almost correct answer is wrong</choicehint></choice>
                        <choice correct="false">Germany</choice>
                        <choice correct="true">Indonesia</choice>
                        <choice correct="false">Russia</choice>
                      </choicegroup>
                    </multiplechoiceresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml,
                                 metadata={'max_attempts': 10},
                                 grader_type='Final Exam')

    def test_status_removed_after_save_before_submit(self):
        """
        Scenario: User should see the status removed when saving after submitting an answer and reloading the page.
        Given that I have loaded the problem page
        And a choice has been selected and submitted
        When I change the choice
        And Save the problem
        And reload the problem page
        Then I should see the save notification and I should not see any indication of problem status
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        problem_page.click_choice("choice_1")
        problem_page.click_submit()
        problem_page.wait_incorrect_notification()
        problem_page.wait_for_expected_status('label.choicegroup_incorrect', 'incorrect')
        problem_page.click_choice("choice_2")
        self.assertFalse(problem_page.is_expected_status_visible('label.choicegroup_incorrect'))
        problem_page.click_save()
        problem_page.wait_for_save_notification()
        # Refresh the page and the status should not be added
        self.courseware_page.visit()
        self.assertFalse(problem_page.is_expected_status_visible('label.choicegroup_incorrect'))
        self.assertTrue(problem_page.is_save_notification_visible())


@attr(shard=9)
class ProblemSubmitButtonMaxAttemptsTest(ProblemsTest):
    """
    Tests that the Submit button disables after the number of max attempts is reached.
    """

    def get_problem(self):
        """
        Problem structure.
        """
        xml = dedent("""
            <problem>
                <label>Which of the following countries has the largest population?</label>
                    <multiplechoiceresponse>
                      <choicegroup type="MultipleChoice">
                        <choice correct="false">Brazil <choicehint>timely feedback -- explain why an almost correct answer is wrong</choicehint></choice>
                        <choice correct="false">Germany</choice>
                        <choice correct="true">Indonesia</choice>
                        <choice correct="false">Russia</choice>
                      </choicegroup>
                    </multiplechoiceresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml,
                                 metadata={'max_attempts': 2},
                                 grader_type='Final Exam')

    def test_max_attempts(self):
        """
        Verifies that the Submit button disables when the max number of attempts is reached.
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)

        # Submit first answer (correct)
        problem_page.click_choice("choice_2")
        self.assertFalse(problem_page.is_submit_disabled())
        problem_page.click_submit()
        problem_page.wait_success_notification()

        # Submit second and final answer (incorrect)
        problem_page.click_choice("choice_1")
        problem_page.click_submit()
        problem_page.wait_incorrect_notification()

        # Make sure that the Submit button disables.
        problem_page.wait_for_submit_disabled()


@attr(shard=9)
class ProblemSubmitButtonPastDueTest(ProblemsTest):
    """
    Tests that the Submit button is disabled if it is past the due date.
    """

    def get_problem(self):
        """
        Problem structure.
        """
        xml = dedent("""
                <problem>
                    <label>Which of the following countries has the largest population?</label>
                        <multiplechoiceresponse>
                          <choicegroup type="MultipleChoice">
                            <choice correct="false">Brazil <choicehint>timely feedback -- explain why an almost correct answer is wrong</choicehint></choice>
                            <choice correct="false">Germany</choice>
                            <choice correct="true">Indonesia</choice>
                            <choice correct="false">Russia</choice>
                          </choicegroup>
                        </multiplechoiceresponse>
                </problem>
            """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml,
                                 metadata={'max_attempts': 2},
                                 grader_type='Final Exam')

    def get_sequential(self):
        """ Subclasses can override this to add a sequential with metadata """
        return XBlockFixtureDesc('sequential', 'Test Subsection', metadata={'due': "2016-10-01T00"})

    def test_past_due(self):
        """
        Verifies that the Submit button disables when the max number of attempts is reached.
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        # Should have Submit button disabled on original rendering.
        problem_page.wait_for_submit_disabled()

        # Select a choice, and make sure that the Submit button remains disabled.
        problem_page.click_choice("choice_2")
        problem_page.wait_for_submit_disabled()


@attr(shard=9)
class ProblemExtendedHintTest(ProblemHintTest, EventsTestMixin):
    """
    Test that extended hint features plumb through to the page html and tracking log.
    """

    def get_problem(self):
        """
        Problem with extended hint features.
        """
        xml = dedent("""
            <problem>
            <p>question text</p>
            <stringresponse answer="A">
                <stringequalhint answer="B">hint</stringequalhint>
                <textline size="20"/>
            </stringresponse>
            <demandhint>
              <hint>demand-hint1</hint>
              <hint>demand-hint2</hint>
            </demandhint>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TITLE', data=xml)

    def test_check_hint(self):
        """
        Test clicking Check shows the extended hint in the problem message.
        """
        self.verify_check_hint(
            'B',
            u'Answer\nIncorrect: hint',
            [
                {
                    'event':
                        {
                            'hint_label': u'Incorrect:',
                            'trigger_type': 'single',
                            'student_answer': [u'B'],
                            'correctness': False,
                            'question_type': 'stringresponse',
                            'hints': [{'text': 'hint'}]
                        }
                }
            ]
        )

    def test_demand_hint(self):
        """
        Test clicking hint button shows the demand hint in its div.
        """
        self.verify_demand_hints(
            u'Hint (1 of 2): demand-hint1',
            u'Hint (1 of 2): demand-hint1\nHint (2 of 2): demand-hint2',
            [
                {'event': {u'hint_index': 0, u'hint_len': 2, u'hint_text': u'demand-hint1'}},
                {'event': {u'hint_index': 1, u'hint_len': 2, u'hint_text': u'demand-hint2'}}
            ]
        )


@attr(shard=9)
class ProblemHintWithHtmlTest(ProblemHintTest, EventsTestMixin):
    """
    Tests that hints containing html get rendered properly
    """

    def get_problem(self):
        """
        Problem with extended hint features.
        """
        xml = dedent("""
            <problem>
            <p>question text</p>
            <stringresponse answer="A">
                <stringequalhint answer="C"><a href="#">aa bb</a> cc</stringequalhint>
                <textline size="20"/>
            </stringresponse>
            <demandhint>
              <hint>aa <a href="#">bb</a> cc</hint>
              <hint><a href="#">dd  ee</a> ff</hint>
            </demandhint>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'PROBLEM HTML HINT TEST', data=xml)

    def test_check_hint(self):
        """
        Test clicking Check shows the extended hint in the problem message.
        """
        self.verify_check_hint(
            'C',
            u'Answer\nIncorrect: aa bb cc',
            [
                {
                    'event':
                        {
                            'hint_label': u'Incorrect:',
                            'trigger_type': 'single',
                            'student_answer': [u'C'],
                            'correctness': False,
                            'question_type': 'stringresponse',
                            'hints': [{'text': '<a href="#">aa bb</a> cc'}]
                        }
                }
            ]
        )

    def test_demand_hint(self):
        """
        Test clicking hint button shows the demand hints in a notification area.
        """
        self.verify_demand_hints(
            u'Hint (1 of 2): aa bb cc',
            u'Hint (1 of 2): aa bb cc\nHint (2 of 2): dd ee ff',
            [
                {'event': {u'hint_index': 0, u'hint_len': 2, u'hint_text': u'aa <a href="#">bb</a> cc'}},
                {'event': {u'hint_index': 1, u'hint_len': 2, u'hint_text': u'<a href="#">dd  ee</a> ff'}}
            ]
        )


@attr(shard=9)
class ProblemWithMathjax(ProblemsTest):
    """
    Tests the <MathJax> used in problem
    """

    def get_problem(self):
        """
        Create a problem with a <MathJax> in body and hint
        """
        xml = dedent(r"""
            <problem>
                <p>Check mathjax has rendered [mathjax]E=mc^2[/mathjax]</p>
                <multiplechoiceresponse>
                  <label>Answer this?</label>
                  <choicegroup type="MultipleChoice">
                    <choice correct="true">Choice1 <choicehint>Correct choice message</choicehint></choice>
                    <choice correct="false">Choice2<choicehint>Wrong choice message</choicehint></choice>
                  </choicegroup>
                </multiplechoiceresponse>
                <demandhint>
                        <hint>mathjax should work1 \(E=mc^2\) </hint>
                        <hint>mathjax should work2 [mathjax]E=mc^2[/mathjax]</hint>
                </demandhint>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'MATHJAX TEST PROBLEM', data=xml)

    @skip('Edraak: Disable until we support SVG output for the Arabic MathJax extension.')
    def test_mathjax_in_hint(self):
        """
        Test that MathJax have successfully rendered in problem hint
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        self.assertEqual(problem_page.problem_name, "MATHJAX TEST PROBLEM")

        problem_page.verify_mathjax_rendered_in_problem()

        # The hint button rotates through multiple hints
        problem_page.click_hint(hint_index=0)
        self.assertEqual(
            ["<strong>Hint (1 of 2): </strong>mathjax should work1"],
            problem_page.extract_hint_text_from_html
        )
        problem_page.verify_mathjax_rendered_in_hint()

        # Rotate the hint and check the problem hint
        problem_page.click_hint(hint_index=1)

        self.assertEqual(
            [
                "<strong>Hint (1 of 2): </strong>mathjax should work1",
                "<strong>Hint (2 of 2): </strong>mathjax should work2"
            ],
            problem_page.extract_hint_text_from_html
        )

        problem_page.verify_mathjax_rendered_in_hint()


@attr(shard=9)
class ProblemPartialCredit(ProblemsTest):
    """
    Makes sure that the partial credit is appearing properly.
    """
    def get_problem(self):
        """
        Create a problem with partial credit.
        """
        xml = dedent("""
            <problem>
                <p>The answer is 1. Partial credit for -1.</p>
                <numericalresponse answer="1" partial_credit="list">
                    <label>How many miles away from Earth is the sun? Use scientific notation to answer.</label>
                    <formulaequationinput/>
                    <responseparam type="tolerance" default="0.01" />
                    <responseparam partial_answers="-1" />
                </numericalresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'PARTIAL CREDIT TEST PROBLEM', data=xml)

    # TODO: Reinstate this, it broke when landing the unified header in LEARNER-
    # def test_partial_credit(self):
    #     """
    #     Test that we can see the partial credit value and feedback.
    #     """
    #     self.courseware_page.visit()
    #     problem_page = ProblemPage(self.browser)
    #     self.assertEqual(problem_page.problem_name, 'PARTIAL CREDIT TEST PROBLEM')
    #     problem_page.fill_answer_numerical('-1')
    #     problem_page.click_submit()
    #     problem_page.wait_for_status_icon()
    #     self.assertTrue(problem_page.simpleprob_is_partially_correct())


@attr(shard=9)
class LogoutDuringAnswering(ProblemsTest):
    """
    Tests for the scenario where a user is logged out (their session expires
    or is revoked) just before they click "check" on a problem.
    """
    def get_problem(self):
        """
        Create a problem.
        """
        xml = dedent("""
            <problem>
                <numericalresponse answer="1">
                    <label>The answer is 1</label>
                    <formulaequationinput/>
                    <responseparam type="tolerance" default="0.01" />
                </numericalresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml)

    def log_user_out(self):
        """
        Log the user out by deleting their session cookie.
        """
        self.browser.delete_cookie('sessionid')

    def test_logout_after_click_redirect(self):
        """
        1) User goes to a problem page.
        2) User fills out an answer to the problem.
        3) User is logged out because their session id is invalidated or removed.
        4) User clicks "check", and sees a confirmation modal asking them to
           re-authenticate, since they've just been logged out.
        5) User clicks "ok".
        6) User is redirected to the login page.
        7) User logs in.
        8) User is redirected back to the problem page they started out on.
        9) User is able to submit an answer
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        self.assertEqual(problem_page.problem_name, 'TEST PROBLEM')
        problem_page.fill_answer_numerical('1')

        self.log_user_out()
        with problem_page.handle_alert(confirm=True):
            problem_page.click_submit()

        login_page = CombinedLoginAndRegisterPage(self.browser)
        login_page.wait_for_page()

        login_page.login(self.email, self.password)

        problem_page.wait_for_page()
        self.assertEqual(problem_page.problem_name, 'TEST PROBLEM')

        problem_page.fill_answer_numerical('1')
        problem_page.click_submit()
        self.assertTrue(problem_page.simpleprob_is_correct())


@attr(shard=9)
class ProblemQuestionDescriptionTest(ProblemsTest):
    """TestCase Class to verify question and description rendering."""
    descriptions = [
        "A vegetable is an edible part of a plant in tuber form.",
        "A fruit is a fertilized ovary of a plant and contains seeds."
    ]

    def get_problem(self):
        """
        Create a problem with question and description.
        """
        xml = dedent("""
            <problem>
                <choiceresponse>
                    <label>Eggplant is a _____?</label>
                    <description>{}</description>
                    <description>{}</description>
                    <checkboxgroup>
                        <choice correct="true">vegetable</choice>
                        <choice correct="false">fruit</choice>
                    </checkboxgroup>
                </choiceresponse>
            </problem>
        """.format(*self.descriptions))
        return XBlockFixtureDesc('problem', 'Label with Description', data=xml)

    def test_question_with_description(self):
        """
        Scenario: Test that question and description are rendered as expected.
        Given I am enrolled in a course.
        When I visit a unit page with a CAPA question.
        Then label and description should be rendered correctly.
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        self.assertEqual(problem_page.problem_name, 'Label with Description')
        self.assertEqual(problem_page.problem_question, 'Eggplant is a _____?')
        self.assertEqual(problem_page.problem_question_descriptions, self.descriptions)


class CAPAProblemA11yBaseTestMixin(object):
    """Base TestCase Class to verify CAPA problem accessibility."""

    def test_a11y(self):
        """
        Verifies that there are no accessibility issues for a particular problem type
        """
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)

        # Set the scope to the problem question
        problem_page.a11y_audit.config.set_scope(
            include=['.wrapper-problem-response']
        )

        # Run the accessibility audit.
        problem_page.a11y_audit.check_for_accessibility_errors()


@attr('a11y')
class CAPAProblemChoiceA11yTest(CAPAProblemA11yBaseTestMixin, ProblemsTest):
    """TestCase Class to verify accessibility for checkboxes and multiplechoice CAPA problems."""

    def get_problem(self):
        """
        Problem structure.
        """
        xml = dedent("""
        <problem>
            <choiceresponse>
                <label>question 1 text here</label>
                <description>description 2 text 1</description>
                <description>description 2 text 2</description>
                <checkboxgroup>
                    <choice correct="true">True</choice>
                    <choice correct="false">False</choice>
                </checkboxgroup>
            </choiceresponse>
            <multiplechoiceresponse>
                <label>question 2 text here</label>
                <description>description 2 text 1</description>
                <description>description 2 text 2</description>
                <choicegroup type="MultipleChoice">
                    <choice correct="false">Alpha <choicehint>A hint</choicehint></choice>
                    <choice correct="true">Beta</choice>
                </choicegroup>
            </multiplechoiceresponse>
         </problem>
        """)
        return XBlockFixtureDesc('problem', 'Problem A11Y TEST', data=xml)


@attr('a11y')
class ProblemTextInputA11yTest(CAPAProblemA11yBaseTestMixin, ProblemsTest):
    """TestCase Class to verify TextInput problem accessibility."""

    def get_problem(self):
        """
        TextInput problem XML.
        """
        xml = dedent("""
        <problem>
            <stringresponse answer="fight" type="ci">
                <label>who wishes to _____ must first count the cost.</label>
                <description>Appear weak when you are strong, and strong when you are weak.</description>
                <description>In the midst of chaos, there is also opportunity.</description>
                <textline size="40"/>
            </stringresponse>
            <stringresponse answer="force" type="ci">
                <label>A leader leads by example not by _____.</label>
                <description>The supreme art of war is to subdue the enemy without fighting.</description>
                <description>Great results, can be achieved with small forces.</description>
                <textline size="40"/>
            </stringresponse>
        </problem>""")
        return XBlockFixtureDesc('problem', 'TEXTINPUT PROBLEM', data=xml)


@attr('a11y')
class CAPAProblemDropDownA11yTest(CAPAProblemA11yBaseTestMixin, ProblemsTest):
    """TestCase Class to verify accessibility for dropdowns(optioninput) CAPA problems."""

    def get_problem(self):
        """
        Problem structure.
        """
        xml = dedent("""
        <problem>
            <optionresponse>
                <p>You can use this template as a guide to the simple editor markdown and OLX markup to use for
                 dropdown problems. Edit this component to replace this template with your own assessment.</p>
                <label>Which of the following is a fruit</label>
                <description>Choose wisely</description>
                <optioninput>
                    <option correct="False">radish</option>
                    <option correct="True">appple</option>
                    <option correct="False">carrot</option>
                </optioninput>
            </optionresponse>
        </problem>
        """)
        return XBlockFixtureDesc('problem', 'Problem A11Y TEST', data=xml)


@attr('a11y')
class ProblemNumericalInputA11yTest(CAPAProblemA11yBaseTestMixin, ProblemsTest):
    """Tests NumericalInput accessibility."""

    def get_problem(self):
        """NumericalInput problem XML."""
        xml = dedent("""
        <problem>
            <numericalresponse answer="10*i">
                <label>The square of what number is -100?</label>
                <description>Use scientific notation to answer.</description>
                <formulaequationinput/>
            </numericalresponse>
        </problem>""")
        return XBlockFixtureDesc('problem', 'NUMERICALINPUT PROBLEM', data=xml)


@attr('a11y')
class ProblemMathExpressionInputA11yTest(CAPAProblemA11yBaseTestMixin, ProblemsTest):
    """Tests MathExpressionInput accessibility."""

    def get_problem(self):
        """MathExpressionInput problem XML."""
        xml = dedent(r"""
        <problem>
            <script type="loncapa/python">
        derivative = "n*x^(n-1)"
            </script>

            <formularesponse type="ci" samples="x,n@1,2:3,4#10" answer="$derivative">
                <label>Let \( x\) be a variable, and let \( n\) be an arbitrary constant. What is the derivative of \( x^n\)?</label>
                <description>Enter the equation</description>
                <responseparam type="tolerance" default="0.00001"/>
                <formulaequationinput size="40"/>
            </formularesponse>
        </problem>""")
        return XBlockFixtureDesc('problem', 'MATHEXPRESSIONINPUT PROBLEM', data=xml)


class ProblemMetaGradedTest(ProblemsTest):
    """
    TestCase Class to verify that the graded variable is passed
    """
    def get_problem(self):
        """
        Problem structure
        """
        xml = dedent("""
            <problem>
                <label>Which of the following countries has the largest population?</label>
                    <multiplechoiceresponse>
                      <choicegroup type="MultipleChoice">
                        <choice correct="false">Brazil <choicehint>timely feedback -- explain why an almost correct answer is wrong</choicehint></choice>
                        <choice correct="false">Germany</choice>
                        <choice correct="true">Indonesia</choice>
                        <choice correct="false">Russia</choice>
                      </choicegroup>
                    </multiplechoiceresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml, grader_type='Final Exam')

    def test_grader_type_displayed(self):
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        self.assertEqual(problem_page.problem_name, 'TEST PROBLEM')
        self.assertEqual(problem_page.problem_progress_graded_value, "1 point possible (graded)")


class ProblemMetaUngradedTest(ProblemsTest):
    """
    TestCase Class to verify that the ungraded variable is passed
    """
    def get_problem(self):
        """
        Problem structure
        """
        xml = dedent("""
            <problem>
                <label>Which of the following countries has the largest population?</label>
                    <multiplechoiceresponse>
                      <choicegroup type="MultipleChoice">
                        <choice correct="false">Brazil <choicehint>timely feedback -- explain why an almost correct answer is wrong</choicehint></choice>
                        <choice correct="false">Germany</choice>
                        <choice correct="true">Indonesia</choice>
                        <choice correct="false">Russia</choice>
                      </choicegroup>
                    </multiplechoiceresponse>
            </problem>
        """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml)

    def test_grader_type_displayed(self):
        self.courseware_page.visit()
        problem_page = ProblemPage(self.browser)
        self.assertEqual(problem_page.problem_name, 'TEST PROBLEM')
        self.assertEqual(problem_page.problem_progress_graded_value, "1 point possible (ungraded)")


class FormulaProblemTest(ProblemsTest):
    """
    Test Class to verify the formula problem on LMS.
    """
    def setUp(self):
        """
        Setup the test suite to verify various behaviors involving formula problem type.

        Given a course, setup a formula problem type and view it in courseware
        Given the MathJax requirement for generating preview, wait for MathJax files to load
        """
        super(FormulaProblemTest, self).setUp()
        self.courseware_page.visit()
        time.sleep(6)

    def get_problem(self):
        """
        creating the formula response problem, with reset button enabled.
        """
        xml = dedent("""
                    <problem>
    <formularesponse type="ci" samples="R_1,R_2,R_3@1,2,3:3,4,5#10" answer="R_1*R_2/R_3">
        <p>You can use this template as a guide to the OLX markup to use for math expression problems. Edit this component to replace the example with your own assessment.</p>
        <label>Add the question text, or prompt, here. This text is required. Example: Write an expression for the product of R_1, R_2, and the inverse of R_3.</label>
        <description>You can add an optional tip or note related to the prompt like this. Example: To test this example, the correct answer is R_1*R_2/R_3</description>
        <responseparam type="tolerance" default="0.00001"/>
        <formulaequationinput size="40"/>
    </formularesponse>
                    </problem>
                """)
        return XBlockFixtureDesc('problem', 'TEST PROBLEM', data=xml, metadata={'show_reset_button': True})

    def test_reset_problem_after_incorrect_submission(self):
        """
        Scenario: Verify that formula problem can be resetted after an incorrect submission.

        Given I am attempting a formula response problem type
        When I input an incorrect answer
        Then the answer preview is generated using MathJax
        When I submit the problem
        Then I can see incorrect status and a reset button
        When I click reset, the input pane contents get clear
        """
        problem_page = ProblemPage(self.browser)
        problem_page.fill_answer_numerical('R_1*R_2')
        problem_page.verify_mathjax_rendered_in_preview()
        problem_page.click_submit()
        self.assertFalse(problem_page.simpleprob_is_correct())
        self.assertTrue(problem_page.is_reset_button_present())
        problem_page.click_reset()
        self.assertEqual(problem_page.get_numerical_input_value, '')

    def test_reset_button_not_rendered_after_correct_submission(self):
        """
        Scenario: Verify that formula problem can not be resetted after an incorrect submission.

        Given I am attempting a formula response problem type
        When I input a correct answer
        Then I should be able to see the mathjax generated preview
        When I submit the answer
        Then the correct status is visible
        And reset button is not rendered
        """
        problem_page = ProblemPage(self.browser)
        problem_page.fill_answer_numerical('R_1*R_2/R_3')
        problem_page.verify_mathjax_rendered_in_preview()
        problem_page.click_submit()
        self.assertTrue(problem_page.simpleprob_is_correct())
        self.assertFalse(problem_page.is_reset_button_present())

    def test_reset_problem_after_changing_correctness(self):
        """
        Scenario: Verify that formula problem can be resetted after changing the correctness.

        Given I am attempting a formula problem type
        When I answer it correctly
        Then the correctness status should be visible
        And reset button is not rendered
        When I change my submission to incorrect
        Then the reset button appears and is clickable
        """
        problem_page = ProblemPage(self.browser)
        problem_page.fill_answer_numerical('R_1*R_2/R_3')
        problem_page.verify_mathjax_rendered_in_preview()
        problem_page.click_submit()
        self.assertTrue(problem_page.simpleprob_is_correct())
        self.assertFalse(problem_page.is_reset_button_present())
        problem_page.fill_answer_numerical('R_1/R_3')
        problem_page.click_submit()
        self.assertFalse(problem_page.simpleprob_is_correct())
        self.assertTrue(problem_page.is_reset_button_present())
        problem_page.click_reset()
        self.assertEqual(problem_page.get_numerical_input_value, '')


@ddt.ddt
class FormulaProblemRandomizeTest(ProblemsTest):
    """
    Test Class to verify the formula problem on LMS with Randomization enabled.
    """

    def setUp(self):
        """
        Setup the test suite to verify various behaviors involving formula problem type.

        Given a course, setup a formula problem type and view it in courseware
        Given the MathJax requirement for generating preview, wait for MathJax files to load
        """
        super(FormulaProblemRandomizeTest, self).setUp()
        self.courseware_page.visit()
        time.sleep(6)

    def get_problem(self):
        """
        creating the formula response problem.
        """
        xml = dedent("""
                    <problem>
    <formularesponse type="ci" samples="R_1,R_2,R_3@1,2,3:3,4,5#10" answer="R_1*R_2/R_3">
        <p>You can use this template as a guide to the OLX markup to use for math expression problems. Edit this component to replace the example with your own assessment.</p>
        <label>Add the question text, or prompt, here. This text is required. Example: Write an expression for the product of R_1, R_2, and the inverse of R_3.</label>
        <description>You can add an optional tip or note related to the prompt like this. Example: To test this example, the correct answer is R_1*R_2/R_3</description>
        <responseparam type="tolerance" default="0.00001"/>
        <formulaequationinput size="40"/>
    </formularesponse>
                    </problem>
                """)

        # rerandomize:always will show reset button, no matter the submission correctness
        return XBlockFixtureDesc(
            'problem', 'TEST PROBLEM', data=xml, metadata={'show_reset_button': True, 'rerandomize': 'always'}
        )

    @ddt.data(
        ('R_1*R_2', 'incorrect'),
        ('R_1/R_3', 'incorrect'),
        ('R_1*R_2/R_3', 'correct')
    )
    @ddt.unpack
    def test_reset_problem_after_submission(self, input_value, correctness):
        """
        Scenario: Test that reset button works regardless the submission correctness status.

        Given I am attempting a formula problem type with randomization:always configuration
        When I input the answer
        Then I should be able to see the MathJax generated preview
        When I submit the problem
        Then I should be able to see the reset button
        When reset button is clicked
        Then the input pane contents should be clear
        """
        problem_page = ProblemPage(self.browser)
        problem_page.fill_answer_numerical(input_value)
        problem_page.verify_mathjax_rendered_in_preview()
        problem_page.click_submit()
        self.assertEqual(problem_page.get_simpleprob_correctness(), correctness)
        self.assertTrue(problem_page.is_reset_button_present())
        problem_page.click_reset()
        self.assertEqual(problem_page.get_numerical_input_value, '')

    @ddt.data(
        ('R_1*R_2', 'incorrect', '0/1 point (ungraded)', '0/1 point (ungraded)'),
        ('R_1*R_2/R_3', 'correct', '1/1 point (ungraded)', '0/1 point (ungraded)'),
        ('R_1/R_2', 'incorrect', '0/1 point (ungraded)', '0/1 point (ungraded)')
    )
    @ddt.unpack
    def test_score_reset_after_resetting_problem(self, input_value, correctness, score_before_reset, score_after_reset):
        """
        Scenario: Test that score resets after the formula problem is resetted.

        Given I am attempting a formula problem type with randomization:always configuration
        When I input the answer
        Then I should be able to see the MathJax generated preview
        When I submit the problem
        Then I should be able to view the score that I received
        And The reset button should be present and is clickable
        When the reset button is clicked
        Then the score resets to zero
        """
        problem_page = ProblemPage(self.browser)
        problem_page.fill_answer_numerical(input_value)
        problem_page.verify_mathjax_rendered_in_preview()
        problem_page.click_submit()
        self.assertEqual(problem_page.get_simpleprob_correctness(), correctness)
        self.assertIn(score_before_reset, problem_page.problem_progress_graded_value)
        self.assertTrue(problem_page.is_reset_button_present())
        problem_page.click_reset()
        self.assertIn(score_after_reset, problem_page.problem_progress_graded_value)

    @ddt.data(
        ('R_1*R_2', 'incorrect', 'R_1*R_2/R_3'),
        ('R_1*R_2/R_3', 'correct', 'R_1/R_3')
    )
    @ddt.unpack
    def test_reset_correctness_after_changing_answer(self, input_value, correctness, next_input):
        """
        Scenario: Test that formula problem can be resetted after changing the answer.

        Given I am attempting a formula problem type with randomization:always configuration
        When I input an answer
        Then the mathjax generated preview should be visible
        When I submit the problem, I can see the correctness status
        When I only input another answer
        Then the correctness status is no longer visible
        And I am able to see the reset button
        And when I click the reset button
        Then input pane contents are cleared
        """
        problem_page = ProblemPage(self.browser)
        problem_page.fill_answer_numerical(input_value)
        problem_page.verify_mathjax_rendered_in_preview()
        problem_page.click_submit()
        self.assertEqual(problem_page.get_simpleprob_correctness(), correctness)
        problem_page.fill_answer_numerical(next_input)
        self.assertIsNone(problem_page.get_simpleprob_correctness())
        self.assertTrue(problem_page.is_reset_button_present())
        problem_page.click_reset()
        self.assertEqual(problem_page.get_numerical_input_value, '')
