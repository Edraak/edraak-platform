"""
Test grading events across apps.
"""

from mock import call as mock_call, patch
from crum import set_current_request

from capa.tests.response_xml_factory import MultipleChoiceResponseXMLFactory
from courseware.tests.test_submitting_problems import ProblemSubmissionTestMixin
from lms.djangoapps.instructor.enrollment import reset_student_attempts
from lms.djangoapps.instructor_task.api import submit_rescore_problem_for_student
from openedx.core.djangolib.testing.utils import get_mock_request
from student.models import CourseEnrollment
from student.tests.factories import UserFactory
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

from ... import events


class GradesEventIntegrationTest(ProblemSubmissionTestMixin, SharedModuleStoreTestCase):
    """
    Tests integration between the eventing in various layers
    of the grading infrastructure.
    """
    shard = 4
    ENABLED_SIGNALS = ['course_published']

    @classmethod
    def reset_course(cls):
        """
        Sets up the course anew.
        """
        with cls.store.default_store(ModuleStoreEnum.Type.split):
            cls.course = CourseFactory.create()
            cls.chapter = ItemFactory.create(
                parent=cls.course,
                category="chapter",
                display_name="Test Chapter"
            )
            cls.sequence = ItemFactory.create(
                parent=cls.chapter,
                category='sequential',
                display_name="Test Sequential 1",
                graded=True,
                format="Homework"
            )
            cls.vertical = ItemFactory.create(
                parent=cls.sequence,
                category='vertical',
                display_name='Test Vertical 1'
            )
            problem_xml = MultipleChoiceResponseXMLFactory().build_xml(
                question_text='The correct answer is Choice 2',
                choices=[False, False, True, False],
                choice_names=['choice_0', 'choice_1', 'choice_2', 'choice_3']
            )
            cls.problem = ItemFactory.create(
                parent=cls.vertical,
                category="problem",
                display_name="p1",
                data=problem_xml,
                metadata={'weight': 2}
            )

    def setUp(self):
        self.reset_course()
        super(GradesEventIntegrationTest, self).setUp()
        self.addCleanup(set_current_request, None)
        self.request = get_mock_request(UserFactory())
        self.student = self.request.user
        self.client.login(username=self.student.username, password="test")
        CourseEnrollment.enroll(self.student, self.course.id)
        self.instructor = UserFactory.create(is_staff=True, username=u'test_instructor', password=u'test')
        self.refresh_course()

    @patch('lms.djangoapps.grades.events.tracker')
    def test_submit_answer(self, events_tracker):
        self.submit_question_answer('p1', {'2_1': 'choice_choice_2'})
        course = self.store.get_course(self.course.id, depth=0)

        event_transaction_id = events_tracker.emit.mock_calls[0][1][1]['event_transaction_id']
        events_tracker.emit.assert_has_calls(
            [
                mock_call(
                    events.PROBLEM_SUBMITTED_EVENT_TYPE,
                    {
                        'user_id': unicode(self.student.id),
                        'event_transaction_id': event_transaction_id,
                        'event_transaction_type': events.PROBLEM_SUBMITTED_EVENT_TYPE,
                        'course_id': unicode(self.course.id),
                        'problem_id': unicode(self.problem.location),
                        'weighted_earned': 2.0,
                        'weighted_possible': 2.0,
                    },
                ),
                mock_call(
                    events.COURSE_GRADE_CALCULATED,
                    {
                        'course_version': unicode(course.course_version),
                        'percent_grade': 0.02,
                        'grading_policy_hash': u'ChVp0lHGQGCevD0t4njna/C44zQ=',
                        'user_id': unicode(self.student.id),
                        'letter_grade': u'',
                        'event_transaction_id': event_transaction_id,
                        'event_transaction_type': events.PROBLEM_SUBMITTED_EVENT_TYPE,
                        'course_id': unicode(self.course.id),
                        'course_edited_timestamp': unicode(course.subtree_edited_on),
                    }
                ),
            ],
            any_order=True,
        )

    def test_delete_student_state(self):
        self.submit_question_answer('p1', {'2_1': 'choice_choice_2'})

        with patch('lms.djangoapps.instructor.enrollment.tracker') as enrollment_tracker:
            with patch('lms.djangoapps.grades.events.tracker') as events_tracker:
                reset_student_attempts(
                    self.course.id, self.student, self.problem.location, self.instructor, delete_module=True,
                )
        course = self.store.get_course(self.course.id, depth=0)

        event_transaction_id = enrollment_tracker.method_calls[0][1][1]['event_transaction_id']
        enrollment_tracker.emit.assert_called_with(
            events.STATE_DELETED_EVENT_TYPE,
            {
                'user_id': unicode(self.student.id),
                'course_id': unicode(self.course.id),
                'problem_id': unicode(self.problem.location),
                'instructor_id': unicode(self.instructor.id),
                'event_transaction_id': event_transaction_id,
                'event_transaction_type': events.STATE_DELETED_EVENT_TYPE,
            }
        )

        events_tracker.emit.assert_called_with(
            events.COURSE_GRADE_CALCULATED,
            {
                'percent_grade': 0.0,
                'grading_policy_hash': u'ChVp0lHGQGCevD0t4njna/C44zQ=',
                'user_id': unicode(self.student.id),
                'letter_grade': u'',
                'event_transaction_id': event_transaction_id,
                'event_transaction_type': events.STATE_DELETED_EVENT_TYPE,
                'course_id': unicode(self.course.id),
                'course_edited_timestamp': unicode(course.subtree_edited_on),
                'course_version': unicode(course.course_version),
            }
        )

    def test_rescoring_events(self):
        self.submit_question_answer('p1', {'2_1': 'choice_choice_3'})
        new_problem_xml = MultipleChoiceResponseXMLFactory().build_xml(
            question_text='The correct answer is Choice 3',
            choices=[False, False, False, True],
            choice_names=['choice_0', 'choice_1', 'choice_2', 'choice_3']
        )
        with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred, self.course.id):
            self.problem.data = new_problem_xml
            self.store.update_item(self.problem, self.instructor.id)
        self.store.publish(self.problem.location, self.instructor.id)

        with patch('lms.djangoapps.grades.events.tracker') as events_tracker:
            submit_rescore_problem_for_student(
                request=get_mock_request(self.instructor),
                usage_key=self.problem.location,
                student=self.student,
                only_if_higher=False
            )
        course = self.store.get_course(self.course.id, depth=0)

        # make sure the tracker's context is updated with course info
        for args in events_tracker.get_tracker().context.call_args_list:
            self.assertEqual(
                args[0][1],
                {'course_id': unicode(self.course.id), 'org_id': unicode(self.course.org)}
            )

        event_transaction_id = events_tracker.emit.mock_calls[0][1][1]['event_transaction_id']
        events_tracker.emit.assert_has_calls(
            [
                mock_call(
                    events.GRADES_RESCORE_EVENT_TYPE,
                    {
                        'course_id': unicode(self.course.id),
                        'user_id': unicode(self.student.id),
                        'problem_id': unicode(self.problem.location),
                        'new_weighted_earned': 2,
                        'new_weighted_possible': 2,
                        'only_if_higher': False,
                        'instructor_id': unicode(self.instructor.id),
                        'event_transaction_id': event_transaction_id,
                        'event_transaction_type': events.GRADES_RESCORE_EVENT_TYPE,
                    },
                ),
                mock_call(
                    events.COURSE_GRADE_CALCULATED,
                    {
                        'course_version': unicode(course.course_version),
                        'percent_grade': 0.02,
                        'grading_policy_hash': u'ChVp0lHGQGCevD0t4njna/C44zQ=',
                        'user_id': unicode(self.student.id),
                        'letter_grade': u'',
                        'event_transaction_id': event_transaction_id,
                        'event_transaction_type': events.GRADES_RESCORE_EVENT_TYPE,
                        'course_id': unicode(self.course.id),
                        'course_edited_timestamp': unicode(course.subtree_edited_on),
                    },
                ),
            ],
            any_order=True,
        )
