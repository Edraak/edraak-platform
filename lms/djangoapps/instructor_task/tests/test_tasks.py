"""
Unit tests for LMS instructor-initiated background tasks.

Runs tasks on answers to course problems to validate that code
paths actually work.
"""

import json
from functools import partial
from uuid import uuid4

import ddt
from celery.states import FAILURE, SUCCESS
from django.utils.translation import ugettext_noop
from mock import MagicMock, Mock, patch
from opaque_keys.edx.locations import i4xEncoder

from course_modes.models import CourseMode
from courseware.models import StudentModule
from courseware.tests.factories import StudentModuleFactory
from lms.djangoapps.instructor_task.exceptions import UpdateProblemModuleStateError
from lms.djangoapps.instructor_task.models import InstructorTask
from lms.djangoapps.instructor_task.tasks import (
    delete_problem_state,
    export_ora2_data,
    generate_certificates,
    rescore_problem,
    reset_problem_attempts,
    override_problem_score
)
from lms.djangoapps.instructor_task.tasks_helper.misc import upload_ora2_data
from lms.djangoapps.instructor_task.tests.factories import InstructorTaskFactory
from lms.djangoapps.instructor_task.tests.test_base import InstructorTaskModuleTestCase
from openedx.core.lib.tests import attr
from xmodule.modulestore.exceptions import ItemNotFoundError

PROBLEM_URL_NAME = "test_urlname"


class TestTaskFailure(Exception):
    """
    An example exception to indicate failure of a mocked task.
    """
    pass


class TestInstructorTasks(InstructorTaskModuleTestCase):
    """
    Ensure tasks behave as expected.
    """

    def setUp(self):
        super(TestInstructorTasks, self).setUp()
        self.initialize_course()
        self.instructor = self.create_instructor('instructor')
        self.location = self.problem_location(PROBLEM_URL_NAME)

    def _create_input_entry(
            self, student_ident=None, use_problem_url=True, course_id=None, only_if_higher=False, score=None
    ):
        """Creates a InstructorTask entry for testing."""
        task_id = str(uuid4())
        task_input = {'only_if_higher': only_if_higher}
        if use_problem_url:
            task_input['problem_url'] = self.location
        if student_ident is not None:
            task_input['student'] = student_ident
        if score is not None:
            task_input['score'] = score

        course_id = course_id or self.course.id
        instructor_task = InstructorTaskFactory.create(
            course_id=course_id,
            requester=self.instructor,
            task_input=json.dumps(task_input, cls=i4xEncoder),
            task_key='dummy value',
            task_id=task_id
        )
        return instructor_task

    def _get_xmodule_instance_args(self):
        """
        Calculate dummy values for parameters needed for instantiating xmodule instances.
        """
        return {
            'xqueue_callback_url_prefix': 'dummy_value',
            'request_info': {
                'username': 'dummy_username',
                'user_id': 'dummy_id',
            },
        }

    def _run_task_with_mock_celery(self, task_class, entry_id, task_id, expected_failure_message=None):
        """Submit a task and mock how celery provides a current_task."""
        self.current_task = Mock()
        self.current_task.request = Mock()
        self.current_task.request.id = task_id
        self.current_task.update_state = Mock()
        if expected_failure_message is not None:
            self.current_task.update_state.side_effect = TestTaskFailure(expected_failure_message)
        task_args = [entry_id, self._get_xmodule_instance_args()]

        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task') as mock_get_task:
            mock_get_task.return_value = self.current_task
            return task_class.apply(task_args, task_id=task_id).get()

    def _test_missing_current_task(self, task_class):
        """Check that a task_class fails when celery doesn't provide a current_task."""
        task_entry = self._create_input_entry()
        with self.assertRaises(ValueError):
            task_class(task_entry.id, self._get_xmodule_instance_args())

    def _test_undefined_course(self, task_class):
        """Run with celery, but with no course defined."""
        task_entry = self._create_input_entry(course_id="bogus/course/id")
        with self.assertRaises(ItemNotFoundError):
            self._run_task_with_mock_celery(task_class, task_entry.id, task_entry.task_id)

    def _test_undefined_problem(self, task_class):
        """Run with celery, but no problem defined."""
        task_entry = self._create_input_entry()
        with self.assertRaises(ItemNotFoundError):
            self._run_task_with_mock_celery(task_class, task_entry.id, task_entry.task_id)

    def _test_run_with_task(self, task_class, action_name, expected_num_succeeded,
                            expected_num_skipped=0, expected_attempted=0, expected_total=0):
        """Run a task and check the number of StudentModules processed."""
        task_entry = self._create_input_entry()
        status = self._run_task_with_mock_celery(task_class, task_entry.id, task_entry.task_id)
        expected_attempted = expected_attempted \
            if expected_attempted else expected_num_succeeded + expected_num_skipped
        expected_total = expected_total \
            if expected_total else expected_num_succeeded + expected_num_skipped
        # check return value
        self.assertEquals(status.get('attempted'), expected_attempted)
        self.assertEquals(status.get('succeeded'), expected_num_succeeded)
        self.assertEquals(status.get('skipped'), expected_num_skipped)
        self.assertEquals(status.get('total'), expected_total)
        self.assertEquals(status.get('action_name'), action_name)
        self.assertGreater(status.get('duration_ms'), 0)
        # compare with entry in table:
        entry = InstructorTask.objects.get(id=task_entry.id)
        self.assertEquals(json.loads(entry.task_output), status)
        self.assertEquals(entry.task_state, SUCCESS)

    def _test_run_with_no_state(self, task_class, action_name):
        """Run with no StudentModules defined for the current problem."""
        self.define_option_problem(PROBLEM_URL_NAME)
        self._test_run_with_task(task_class, action_name, 0)

    def _create_students_with_state(self, num_students, state=None, grade=0, max_grade=1):
        """Create students, a problem, and StudentModule objects for testing"""
        self.define_option_problem(PROBLEM_URL_NAME)
        enrolled_students = self._create_and_enroll_students(num_students)

        for student in enrolled_students:
            StudentModuleFactory.create(
                course_id=self.course.id,
                module_state_key=self.location,
                student=student,
                grade=grade,
                max_grade=max_grade,
                state=state
            )
        return enrolled_students

    def _create_and_enroll_students(self, num_students, mode=CourseMode.DEFAULT_MODE_SLUG):
        """Create & enroll students for testing"""
        return [
            self.create_student(username='robot%d' % i, email='robot+test+%d@edx.org' % i, mode=mode)
            for i in xrange(num_students)
        ]

    def _create_students_with_no_state(self, num_students):
        """Create students and a problem for testing"""
        self.define_option_problem(PROBLEM_URL_NAME)
        enrolled_students = self._create_and_enroll_students(num_students)
        return enrolled_students

    def _assert_num_attempts(self, students, num_attempts):
        """Check the number attempts for all students is the same"""
        for student in students:
            module = StudentModule.objects.get(course_id=self.course.id,
                                               student=student,
                                               module_state_key=self.location)
            state = json.loads(module.state)
            self.assertEquals(state['attempts'], num_attempts)

    def _test_run_with_failure(self, task_class, expected_message):
        """Run a task and trigger an artificial failure with the given message."""
        task_entry = self._create_input_entry()
        self.define_option_problem(PROBLEM_URL_NAME)
        with self.assertRaises(TestTaskFailure):
            self._run_task_with_mock_celery(task_class, task_entry.id, task_entry.task_id, expected_message)
        # compare with entry in table:
        entry = InstructorTask.objects.get(id=task_entry.id)
        self.assertEquals(entry.task_state, FAILURE)
        output = json.loads(entry.task_output)
        self.assertEquals(output['exception'], 'TestTaskFailure')
        self.assertEquals(output['message'], expected_message)

    def _test_run_with_long_error_msg(self, task_class):
        """
        Run with an error message that is so long it will require
        truncation (as well as the jettisoning of the traceback).
        """
        task_entry = self._create_input_entry()
        self.define_option_problem(PROBLEM_URL_NAME)
        expected_message = "x" * 1500
        with self.assertRaises(TestTaskFailure):
            self._run_task_with_mock_celery(task_class, task_entry.id, task_entry.task_id, expected_message)
        # compare with entry in table:
        entry = InstructorTask.objects.get(id=task_entry.id)
        self.assertEquals(entry.task_state, FAILURE)
        self.assertGreater(1023, len(entry.task_output))
        output = json.loads(entry.task_output)
        self.assertEquals(output['exception'], 'TestTaskFailure')
        self.assertEquals(output['message'], expected_message[:len(output['message']) - 3] + "...")
        self.assertNotIn('traceback', output)

    def _test_run_with_short_error_msg(self, task_class):
        """
        Run with an error message that is short enough to fit
        in the output, but long enough that the traceback won't.
        Confirm that the traceback is truncated.
        """
        task_entry = self._create_input_entry()
        self.define_option_problem(PROBLEM_URL_NAME)
        expected_message = "x" * 900
        with self.assertRaises(TestTaskFailure):
            self._run_task_with_mock_celery(task_class, task_entry.id, task_entry.task_id, expected_message)
        # compare with entry in table:
        entry = InstructorTask.objects.get(id=task_entry.id)
        self.assertEquals(entry.task_state, FAILURE)
        self.assertGreater(1023, len(entry.task_output))
        output = json.loads(entry.task_output)
        self.assertEquals(output['exception'], 'TestTaskFailure')
        self.assertEquals(output['message'], expected_message)
        self.assertEquals(output['traceback'][-3:], "...")


class TestOverrideScoreInstructorTask(TestInstructorTasks):
    """Tests instructor task to override learner's problem score"""
    def assert_task_output(self, output, **expected_output):
        """
        Check & compare output of the task
        """
        self.assertEqual(output.get('total'), expected_output.get('total'))
        self.assertEqual(output.get('attempted'), expected_output.get('attempted'))
        self.assertEqual(output.get('succeeded'), expected_output.get('succeeded'))
        self.assertEqual(output.get('skipped'), expected_output.get('skipped'))
        self.assertEqual(output.get('failed'), expected_output.get('failed'))
        self.assertEqual(output.get('action_name'), expected_output.get('action_name'))
        self.assertGreater(output.get('duration_ms'), expected_output.get('duration_ms', 0))

    def get_task_output(self, task_id):
        """Get and load instructor task output"""
        entry = InstructorTask.objects.get(id=task_id)
        return json.loads(entry.task_output)

    def test_override_missing_current_task(self):
        self._test_missing_current_task(override_problem_score)

    def test_override_undefined_course(self):
        """Tests that override problem score raises exception with undefined course"""
        self._test_undefined_course(override_problem_score)

    def test_override_undefined_problem(self):
        """Tests that override problem score raises exception with undefined problem"""
        self._test_undefined_problem(override_problem_score)

    def test_override_with_no_state(self):
        """Tests override score with no problem state in StudentModule"""
        self._test_run_with_no_state(override_problem_score, 'overridden')

    def test_override_with_failure(self):
        self._test_run_with_failure(override_problem_score, 'We expected this to fail')

    def test_override_with_long_error_msg(self):
        self._test_run_with_long_error_msg(override_problem_score)

    def test_override_with_short_error_msg(self):
        self._test_run_with_short_error_msg(override_problem_score)

    def test_overriding_non_scorable(self):
        """
        Tests that override problem score raises an error if module descriptor has not `set_score` method.
        """
        input_state = json.dumps({'done': True})
        num_students = 1
        self._create_students_with_state(num_students, input_state)
        task_entry = self._create_input_entry(score=0)
        mock_instance = MagicMock()
        del mock_instance.set_score
        with patch(
                'lms.djangoapps.instructor_task.tasks_helper.module_state.get_module_for_descriptor_internal'
        ) as mock_get_module:
            mock_get_module.return_value = mock_instance
            with self.assertRaises(UpdateProblemModuleStateError):
                self._run_task_with_mock_celery(override_problem_score, task_entry.id, task_entry.task_id)
        # check values stored in table:
        entry = InstructorTask.objects.get(id=task_entry.id)
        output = json.loads(entry.task_output)
        self.assertEquals(output['exception'], "UpdateProblemModuleStateError")
        self.assertEquals(output['message'], "Scores cannot be overridden for this problem type.")
        self.assertGreater(len(output['traceback']), 0)

    def test_overriding_unaccessable(self):
        """
        Tests score override for a problem in a course, for all students fails if user has answered a
        problem to which user does not have access to.
        """
        input_state = json.dumps({'done': True})
        num_students = 1
        self._create_students_with_state(num_students, input_state)
        task_entry = self._create_input_entry(score=0)
        with patch('lms.djangoapps.instructor_task.tasks_helper.module_state.get_module_for_descriptor_internal',
                   return_value=None):
            self._run_task_with_mock_celery(override_problem_score, task_entry.id, task_entry.task_id)

        self.assert_task_output(
            output=self.get_task_output(task_entry.id),
            total=num_students,
            attempted=num_students,
            succeeded=0,
            skipped=0,
            failed=num_students,
            action_name='overridden'
        )

    def test_overriding_success(self):
        """
        Tests score override for a problem in a course, for all students succeeds.
        """
        mock_instance = MagicMock()
        getattr(mock_instance, 'override_problem_score').return_value = None

        num_students = 10
        self._create_students_with_state(num_students)
        task_entry = self._create_input_entry(score=0)
        with patch(
                'lms.djangoapps.instructor_task.tasks_helper.module_state.get_module_for_descriptor_internal'
        ) as mock_get_module:
            mock_get_module.return_value = mock_instance
            self._run_task_with_mock_celery(override_problem_score, task_entry.id, task_entry.task_id)

        self.assert_task_output(
            output=self.get_task_output(task_entry.id),
            total=num_students,
            attempted=num_students,
            succeeded=num_students,
            skipped=0,
            failed=0,
            action_name='overridden'
        )

    def test_overriding_success_with_no_state(self):
        """
        Tests that score override is successful for a learner when they have no state.
        """
        num_students = 1
        enrolled_students = self._create_students_with_no_state(num_students=num_students)
        task_entry = self._create_input_entry(score=1, student_ident=enrolled_students[0].username)

        self._run_task_with_mock_celery(override_problem_score, task_entry.id, task_entry.task_id)
        self.assert_task_output(
            output=self.get_task_output(task_entry.id),
            total=num_students,
            attempted=num_students,
            succeeded=num_students,
            skipped=0,
            failed=0,
            action_name='overridden'
        )


@attr(shard=3)
@ddt.ddt
class TestRescoreInstructorTask(TestInstructorTasks):
    """Tests problem-rescoring instructor task."""

    def assert_task_output(self, output, **expected_output):
        """
        Check & compare output of the task
        """
        self.assertEqual(output.get('total'), expected_output.get('total'))
        self.assertEqual(output.get('attempted'), expected_output.get('attempted'))
        self.assertEqual(output.get('succeeded'), expected_output.get('succeeded'))
        self.assertEqual(output.get('skipped'), expected_output.get('skipped'))
        self.assertEqual(output.get('failed'), expected_output.get('failed'))
        self.assertEqual(output.get('action_name'), expected_output.get('action_name'))
        self.assertGreater(output.get('duration_ms'), expected_output.get('duration_ms', 0))

    def get_task_output(self, task_id):
        """Get and load instructor task output"""
        entry = InstructorTask.objects.get(id=task_id)
        return json.loads(entry.task_output)

    def test_rescore_missing_current_task(self):
        self._test_missing_current_task(rescore_problem)

    def test_rescore_undefined_course(self):
        self._test_undefined_course(rescore_problem)

    def test_rescore_undefined_problem(self):
        self._test_undefined_problem(rescore_problem)

    def test_rescore_with_no_state(self):
        self._test_run_with_no_state(rescore_problem, 'rescored')

    def test_rescore_with_failure(self):
        self._test_run_with_failure(rescore_problem, 'We expected this to fail')

    def test_rescore_with_long_error_msg(self):
        self._test_run_with_long_error_msg(rescore_problem)

    def test_rescore_with_short_error_msg(self):
        self._test_run_with_short_error_msg(rescore_problem)

    def test_rescoring_unrescorable(self):
        input_state = json.dumps({'done': True})
        num_students = 1
        self._create_students_with_state(num_students, input_state)
        task_entry = self._create_input_entry()
        mock_instance = MagicMock()
        del mock_instance.rescore_problem
        del mock_instance.rescore
        with patch('lms.djangoapps.instructor_task.tasks_helper.module_state.get_module_for_descriptor_internal') as mock_get_module:
            mock_get_module.return_value = mock_instance
            with self.assertRaises(UpdateProblemModuleStateError):
                self._run_task_with_mock_celery(rescore_problem, task_entry.id, task_entry.task_id)
        # check values stored in table:
        entry = InstructorTask.objects.get(id=task_entry.id)
        output = json.loads(entry.task_output)
        self.assertEquals(output['exception'], "UpdateProblemModuleStateError")
        self.assertEquals(output['message'], "Specified module {0} of type {1} does not support rescoring.".format(
            self.location,
            mock_instance.__class__,
        ))
        self.assertGreater(len(output['traceback']), 0)

    def test_rescoring_unaccessable(self):
        """
        Tests rescores a problem in a course, for all students fails if user has answered a
        problem to which user does not have access to.
        """
        input_state = json.dumps({'done': True})
        num_students = 1
        self._create_students_with_state(num_students, input_state)
        task_entry = self._create_input_entry()
        with patch('lms.djangoapps.instructor_task.tasks_helper.module_state.get_module_for_descriptor_internal', return_value=None):
            self._run_task_with_mock_celery(rescore_problem, task_entry.id, task_entry.task_id)

        self.assert_task_output(
            output=self.get_task_output(task_entry.id),
            total=num_students,
            attempted=num_students,
            succeeded=0,
            skipped=0,
            failed=num_students,
            action_name='rescored'
        )

    def test_rescoring_success(self):
        """
        Tests rescores a problem in a course, for all students succeeds.
        """
        mock_instance = MagicMock()
        getattr(mock_instance, 'rescore').return_value = None
        mock_instance.has_submitted_answer.return_value = True
        del mock_instance.done  # old CAPA code used to use this value so we delete it here to be sure

        num_students = 10
        self._create_students_with_state(num_students)
        task_entry = self._create_input_entry()
        with patch(
                'lms.djangoapps.instructor_task.tasks_helper.module_state.get_module_for_descriptor_internal'
        ) as mock_get_module:
            mock_get_module.return_value = mock_instance
            self._run_task_with_mock_celery(rescore_problem, task_entry.id, task_entry.task_id)

        self.assert_task_output(
            output=self.get_task_output(task_entry.id),
            total=num_students,
            attempted=num_students,
            succeeded=num_students,
            skipped=0,
            failed=0,
            action_name='rescored'
        )


@attr(shard=3)
class TestResetAttemptsInstructorTask(TestInstructorTasks):
    """Tests instructor task that resets problem attempts."""

    def test_reset_missing_current_task(self):
        self._test_missing_current_task(reset_problem_attempts)

    def test_reset_undefined_course(self):
        self._test_undefined_course(reset_problem_attempts)

    def test_reset_undefined_problem(self):
        self._test_undefined_problem(reset_problem_attempts)

    def test_reset_with_no_state(self):
        self._test_run_with_no_state(reset_problem_attempts, 'reset')

    def test_reset_with_failure(self):
        self._test_run_with_failure(reset_problem_attempts, 'We expected this to fail')

    def test_reset_with_long_error_msg(self):
        self._test_run_with_long_error_msg(reset_problem_attempts)

    def test_reset_with_short_error_msg(self):
        self._test_run_with_short_error_msg(reset_problem_attempts)

    def test_reset_with_some_state(self):
        initial_attempts = 3
        input_state = json.dumps({'attempts': initial_attempts})
        num_students = 10
        students = self._create_students_with_state(num_students, input_state)
        # check that entries were set correctly
        self._assert_num_attempts(students, initial_attempts)
        # run the task
        self._test_run_with_task(reset_problem_attempts, 'reset', num_students)
        # check that entries were reset
        self._assert_num_attempts(students, 0)

    def test_reset_with_zero_attempts(self):
        initial_attempts = 0
        input_state = json.dumps({'attempts': initial_attempts})
        num_students = 10
        students = self._create_students_with_state(num_students, input_state)
        # check that entries were set correctly
        self._assert_num_attempts(students, initial_attempts)
        # run the task
        self._test_run_with_task(reset_problem_attempts, 'reset', 0, expected_num_skipped=num_students)
        # check that entries were reset
        self._assert_num_attempts(students, 0)

    def _test_reset_with_student(self, use_email):
        """Run a reset task for one student, with several StudentModules for the problem defined."""
        num_students = 10
        initial_attempts = 3
        input_state = json.dumps({'attempts': initial_attempts})
        students = self._create_students_with_state(num_students, input_state)
        # check that entries were set correctly
        for student in students:
            module = StudentModule.objects.get(course_id=self.course.id,
                                               student=student,
                                               module_state_key=self.location)
            state = json.loads(module.state)
            self.assertEquals(state['attempts'], initial_attempts)

        if use_email:
            student_ident = students[3].email
        else:
            student_ident = students[3].username
        task_entry = self._create_input_entry(student_ident)

        status = self._run_task_with_mock_celery(reset_problem_attempts, task_entry.id, task_entry.task_id)
        # check return value
        self.assertEquals(status.get('attempted'), 1)
        self.assertEquals(status.get('succeeded'), 1)
        self.assertEquals(status.get('total'), 1)
        self.assertEquals(status.get('action_name'), 'reset')
        self.assertGreater(status.get('duration_ms'), 0)

        # compare with entry in table:
        entry = InstructorTask.objects.get(id=task_entry.id)
        self.assertEquals(json.loads(entry.task_output), status)
        self.assertEquals(entry.task_state, SUCCESS)
        # check that the correct entry was reset
        for index, student in enumerate(students):
            module = StudentModule.objects.get(course_id=self.course.id,
                                               student=student,
                                               module_state_key=self.location)
            state = json.loads(module.state)
            if index == 3:
                self.assertEquals(state['attempts'], 0)
            else:
                self.assertEquals(state['attempts'], initial_attempts)

    def test_reset_with_student_username(self):
        self._test_reset_with_student(False)

    def test_reset_with_student_email(self):
        self._test_reset_with_student(True)


@attr(shard=3)
class TestDeleteStateInstructorTask(TestInstructorTasks):
    """Tests instructor task that deletes problem state."""

    def test_delete_missing_current_task(self):
        self._test_missing_current_task(delete_problem_state)

    def test_delete_undefined_course(self):
        self._test_undefined_course(delete_problem_state)

    def test_delete_undefined_problem(self):
        self._test_undefined_problem(delete_problem_state)

    def test_delete_with_no_state(self):
        self._test_run_with_no_state(delete_problem_state, 'deleted')

    def test_delete_with_failure(self):
        self._test_run_with_failure(delete_problem_state, 'We expected this to fail')

    def test_delete_with_long_error_msg(self):
        self._test_run_with_long_error_msg(delete_problem_state)

    def test_delete_with_short_error_msg(self):
        self._test_run_with_short_error_msg(delete_problem_state)

    def test_delete_with_some_state(self):
        # This will create StudentModule entries -- we don't have to worry about
        # the state inside them.
        num_students = 10
        students = self._create_students_with_state(num_students)
        # check that entries were created correctly
        for student in students:
            StudentModule.objects.get(course_id=self.course.id,
                                      student=student,
                                      module_state_key=self.location)
        self._test_run_with_task(delete_problem_state, 'deleted', num_students)
        # confirm that no state can be found anymore:
        for student in students:
            with self.assertRaises(StudentModule.DoesNotExist):
                StudentModule.objects.get(course_id=self.course.id,
                                          student=student,
                                          module_state_key=self.location)


class TestCertificateGenerationnstructorTask(TestInstructorTasks):
    """Tests instructor task that generates student certificates."""

    def test_generate_certificates_missing_current_task(self):
        """
        Test error is raised when certificate generation task run without current task
        """
        self._test_missing_current_task(generate_certificates)

    def test_generate_certificates_task_run(self):
        """
        Test certificate generation task run without any errors
        """
        self._test_run_with_task(
            generate_certificates,
            'certificates generated',
            0,
            0,
            expected_attempted=1,
            expected_total=1
        )


class TestOra2ResponsesInstructorTask(TestInstructorTasks):
    """Tests instructor task that fetches ora2 response data."""

    def test_ora2_missing_current_task(self):
        self._test_missing_current_task(export_ora2_data)

    def test_ora2_with_failure(self):
        self._test_run_with_failure(export_ora2_data, 'We expected this to fail')

    def test_ora2_with_long_error_msg(self):
        self._test_run_with_long_error_msg(export_ora2_data)

    def test_ora2_with_short_error_msg(self):
        self._test_run_with_short_error_msg(export_ora2_data)

    def test_ora2_runs_task(self):
        task_entry = self._create_input_entry()
        task_xmodule_args = self._get_xmodule_instance_args()

        with patch('lms.djangoapps.instructor_task.tasks.run_main_task') as mock_main_task:
            export_ora2_data(task_entry.id, task_xmodule_args)

            action_name = ugettext_noop('generated')
            task_fn = partial(upload_ora2_data, task_xmodule_args)

            mock_main_task.assert_called_once_with_args(task_entry.id, task_fn, action_name)
