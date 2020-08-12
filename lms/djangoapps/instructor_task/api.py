"""
API for submitting background tasks by an instructor for a course.

Also includes methods for getting information about tasks that have
already been submitted, filtered either by running state or input
arguments.

"""
import hashlib
from collections import Counter

from celery.states import READY_STATES

from bulk_email.models import CourseEmail
from lms.djangoapps.certificates.models import CertificateGenerationHistory
from lms.djangoapps.instructor_task.api_helper import (
    check_arguments_for_rescoring,
    check_arguments_for_overriding,
    check_entrance_exam_problems_for_rescoring,
    encode_entrance_exam_and_student_input,
    encode_problem_and_student_input,
    submit_task
)
from lms.djangoapps.instructor_task.models import InstructorTask
from lms.djangoapps.instructor_task.tasks import (
    override_problem_score,
    calculate_grades_csv,
    calculate_may_enroll_csv,
    calculate_problem_grade_report,
    calculate_problem_responses_csv,
    calculate_students_features_csv,
    cohort_students,
    course_survey_report_csv,
    delete_problem_state,
    enrollment_report_features_csv,
    exec_summary_report_csv,
    export_ora2_data,
    generate_certificates,
    proctored_exam_results_csv,
    rescore_problem,
    reset_problem_attempts,
    send_bulk_course_email
)
from util import milestones_helpers
from xmodule.modulestore.django import modulestore


class SpecificStudentIdMissingError(Exception):
    """
    Exception indicating that a student id was not provided when generating a certificate for a specific student.
    """
    pass


def get_running_instructor_tasks(course_id):
    """
    Returns a query of InstructorTask objects of running tasks for a given course.

    Used to generate a list of tasks to display on the instructor dashboard.
    """
    instructor_tasks = InstructorTask.objects.filter(course_id=course_id)
    # exclude states that are "ready" (i.e. not "running", e.g. failure, success, revoked):
    for state in READY_STATES:
        instructor_tasks = instructor_tasks.exclude(task_state=state)
    return instructor_tasks.order_by('-id')


def get_instructor_task_history(course_id, usage_key=None, student=None, task_type=None):
    """
    Returns a query of InstructorTask objects of historical tasks for a given course,
    that optionally match a particular problem, a student, and/or a task type.
    """
    instructor_tasks = InstructorTask.objects.filter(course_id=course_id)
    if usage_key is not None or student is not None:
        _, task_key = encode_problem_and_student_input(usage_key, student)
        instructor_tasks = instructor_tasks.filter(task_key=task_key)
    if task_type is not None:
        instructor_tasks = instructor_tasks.filter(task_type=task_type)

    return instructor_tasks.order_by('-id')


def get_entrance_exam_instructor_task_history(course_id, usage_key=None, student=None):
    """
    Returns a query of InstructorTask objects of historical tasks for a given course,
    that optionally match an entrance exam and student if present.
    """
    instructor_tasks = InstructorTask.objects.filter(course_id=course_id)
    if usage_key is not None or student is not None:
        _, task_key = encode_entrance_exam_and_student_input(usage_key, student)
        instructor_tasks = instructor_tasks.filter(task_key=task_key)

    return instructor_tasks.order_by('-id')


# Disabling invalid-name because this fn name is longer than 30 chars.
def submit_rescore_problem_for_student(request, usage_key, student, only_if_higher=False):
    """
    Request a problem to be rescored as a background task.

    The problem will be rescored for the specified student only.  Parameters are the `course_id`,
    the `problem_url`, and the `student` as a User object.
    The url must specify the location of the problem, using i4x-type notation.

    ItemNotFoundException is raised if the problem doesn't exist, or AlreadyRunningError
    if the problem is already being rescored for this student, or NotImplementedError if
    the problem doesn't support rescoring.
    """
    # check arguments:  let exceptions return up to the caller.
    check_arguments_for_rescoring(usage_key)

    task_type = 'rescore_problem_if_higher' if only_if_higher else 'rescore_problem'
    task_class = rescore_problem
    task_input, task_key = encode_problem_and_student_input(usage_key, student)
    task_input.update({'only_if_higher': only_if_higher})
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_override_score(request, usage_key, student, score):
    """
    Request a problem score override as a background task. Only
    applicable to individual users.

    The problem score will be overridden for the specified student only.
    Parameters are the `course_id`, the `problem_url`, the `student` as
    a User object, and the score override desired.
    The url must specify the location of the problem, using i4x-type notation.

    ItemNotFoundException is raised if the problem doesn't exist, or AlreadyRunningError
    if this task is already running for this student, or NotImplementedError if
    the problem is not a ScorableXBlock.
    """
    check_arguments_for_overriding(usage_key, score)
    task_type = override_problem_score.__name__
    task_class = override_problem_score
    task_input, task_key = encode_problem_and_student_input(usage_key, student)
    task_input['score'] = score
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_rescore_problem_for_all_students(request, usage_key, only_if_higher=False):
    """
    Request a problem to be rescored as a background task.

    The problem will be rescored for all students who have accessed the
    particular problem in a course and have provided and checked an answer.
    Parameters are the `course_id` and the `problem_url`.
    The url must specify the location of the problem, using i4x-type notation.

    ItemNotFoundException is raised if the problem doesn't exist, or AlreadyRunningError
    if the problem is already being rescored, or NotImplementedError if the problem doesn't
    support rescoring.
    """
    # check arguments:  let exceptions return up to the caller.
    check_arguments_for_rescoring(usage_key)

    # check to see if task is already running, and reserve it otherwise
    task_type = 'rescore_problem_if_higher' if only_if_higher else 'rescore_problem'
    task_class = rescore_problem
    task_input, task_key = encode_problem_and_student_input(usage_key)
    task_input.update({'only_if_higher': only_if_higher})
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_rescore_entrance_exam_for_student(request, usage_key, student=None, only_if_higher=False):
    """
    Request entrance exam problems to be re-scored as a background task.

    The entrance exam problems will be re-scored for given student or if student
    is None problems for all students who have accessed the entrance exam.

    Parameters are `usage_key`, which must be a :class:`Location`
    representing entrance exam section and the `student` as a User object.

    ItemNotFoundError is raised if entrance exam does not exists for given
    usage_key, AlreadyRunningError is raised if the entrance exam
    is already being re-scored, or NotImplementedError if the problem doesn't
    support rescoring.
    """
    # check problems for rescoring:  let exceptions return up to the caller.
    check_entrance_exam_problems_for_rescoring(usage_key)

    # check to see if task is already running, and reserve it otherwise
    task_type = 'rescore_problem_if_higher' if only_if_higher else 'rescore_problem'
    task_class = rescore_problem
    task_input, task_key = encode_entrance_exam_and_student_input(usage_key, student)
    task_input.update({'only_if_higher': only_if_higher})
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_reset_problem_attempts_for_all_students(request, usage_key):  # pylint: disable=invalid-name
    """
    Request to have attempts reset for a problem as a background task.

    The problem's attempts will be reset for all students who have accessed the
    particular problem in a course.  Parameters are the `course_id` and
    the `usage_key`, which must be a :class:`Location`.

    ItemNotFoundException is raised if the problem doesn't exist, or AlreadyRunningError
    if the problem is already being reset.
    """
    # check arguments:  make sure that the usage_key is defined
    # (since that's currently typed in).  If the corresponding module descriptor doesn't exist,
    # an exception will be raised.  Let it pass up to the caller.
    modulestore().get_item(usage_key)

    task_type = 'reset_problem_attempts'
    task_class = reset_problem_attempts
    task_input, task_key = encode_problem_and_student_input(usage_key)
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_reset_problem_attempts_in_entrance_exam(request, usage_key, student):  # pylint: disable=invalid-name
    """
    Request to have attempts reset for a entrance exam as a background task.

    Problem attempts for all problems in entrance exam will be reset
    for specified student. If student is None problem attempts will be
    reset for all students.

    Parameters are `usage_key`, which must be a :class:`Location`
    representing entrance exam section and the `student` as a User object.

    ItemNotFoundError is raised if entrance exam does not exists for given
    usage_key, AlreadyRunningError is raised if the entrance exam
    is already being reset.
    """
    # check arguments:  make sure entrance exam(section) exists for given usage_key
    modulestore().get_item(usage_key)

    task_type = 'reset_problem_attempts'
    task_class = reset_problem_attempts
    task_input, task_key = encode_entrance_exam_and_student_input(usage_key, student)
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_delete_problem_state_for_all_students(request, usage_key):  # pylint: disable=invalid-name
    """
    Request to have state deleted for a problem as a background task.

    The problem's state will be deleted for all students who have accessed the
    particular problem in a course.  Parameters are the `course_id` and
    the `usage_key`, which must be a :class:`Location`.

    ItemNotFoundException is raised if the problem doesn't exist, or AlreadyRunningError
    if the particular problem's state is already being deleted.
    """
    # check arguments:  make sure that the usage_key is defined
    # (since that's currently typed in).  If the corresponding module descriptor doesn't exist,
    # an exception will be raised.  Let it pass up to the caller.
    modulestore().get_item(usage_key)

    task_type = 'delete_problem_state'
    task_class = delete_problem_state
    task_input, task_key = encode_problem_and_student_input(usage_key)
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_delete_entrance_exam_state_for_student(request, usage_key, student):  # pylint: disable=invalid-name
    """
    Requests reset of state for entrance exam as a background task.

    Module state for all problems in entrance exam will be deleted
    for specified student.

    All User Milestones of entrance exam will be removed for the specified student

    Parameters are `usage_key`, which must be a :class:`Location`
    representing entrance exam section and the `student` as a User object.

    ItemNotFoundError is raised if entrance exam does not exists for given
    usage_key, AlreadyRunningError is raised if the entrance exam
    is already being reset.
    """
    # check arguments:  make sure entrance exam(section) exists for given usage_key
    modulestore().get_item(usage_key)

    # Remove Content milestones that user has completed
    milestones_helpers.remove_course_content_user_milestones(
        course_key=usage_key.course_key,
        content_key=usage_key,
        user=student,
        relationship='fulfills'
    )

    task_type = 'delete_problem_state'
    task_class = delete_problem_state
    task_input, task_key = encode_entrance_exam_and_student_input(usage_key, student)
    return submit_task(request, task_type, task_class, usage_key.course_key, task_input, task_key)


def submit_bulk_course_email(request, course_key, email_id):
    """
    Request to have bulk email sent as a background task.

    The specified CourseEmail object will be sent be updated for all students who have enrolled
    in a course.  Parameters are the `course_key` and the `email_id`, the id of the CourseEmail object.

    AlreadyRunningError is raised if the same recipients are already being emailed with the same
    CourseEmail object.
    """
    # Assume that the course is defined, and that the user has already been verified to have
    # appropriate access to the course. But make sure that the email exists.
    # We also pull out the targets argument here, so that is displayed in
    # the InstructorTask status.
    email_obj = CourseEmail.objects.get(id=email_id)
    # task_input has a limit to the size it can store, so any target_type with count > 1 is combined and counted
    targets = Counter([target.target_type for target in email_obj.targets.all()])
    targets = [
        target if count <= 1 else
        "{} {}".format(count, target)
        for target, count in targets.iteritems()
    ]

    task_type = 'bulk_course_email'
    task_class = send_bulk_course_email
    task_input = {'email_id': email_id, 'to_option': targets}
    task_key_stub = str(email_id)
    # create the key value by using MD5 hash:
    task_key = hashlib.md5(task_key_stub).hexdigest()
    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_calculate_problem_responses_csv(request, course_key, problem_location):
    """
    Submits a task to generate a CSV file containing all student
    answers to a given problem.

    Raises AlreadyRunningError if said file is already being updated.
    """
    task_type = 'problem_responses_csv'
    task_class = calculate_problem_responses_csv
    task_input = {'problem_location': problem_location, 'user_id': request.user.pk}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_calculate_grades_csv(request, course_key):
    """
    AlreadyRunningError is raised if the course's grades are already being updated.
    """
    task_type = 'grade_course'
    task_class = calculate_grades_csv
    task_input = {}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_problem_grade_report(request, course_key):
    """
    Submits a task to generate a CSV grade report containing problem
    values.
    """
    task_type = 'grade_problems'
    task_class = calculate_problem_grade_report
    task_input = {}
    task_key = ""
    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_calculate_students_features_csv(request, course_key, features):
    """
    Submits a task to generate a CSV containing student profile info.

    Raises AlreadyRunningError if said CSV is already being updated.
    """
    task_type = 'profile_info_csv'
    task_class = calculate_students_features_csv
    task_input = features
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_detailed_enrollment_features_csv(request, course_key):
    """
    Submits a task to generate a CSV containing detailed enrollment info.

    Raises AlreadyRunningError if said CSV is already being updated.
    """
    task_type = 'detailed_enrollment_report'
    task_class = enrollment_report_features_csv
    task_input = {}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_calculate_may_enroll_csv(request, course_key, features):
    """
    Submits a task to generate a CSV file containing information about
    invited students who have not enrolled in a given course yet.

    Raises AlreadyRunningError if said file is already being updated.
    """
    task_type = 'may_enroll_info_csv'
    task_class = calculate_may_enroll_csv
    task_input = {'features': features}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_executive_summary_report(request, course_key):
    """
    Submits a task to generate a HTML File containing the executive summary report.

    Raises AlreadyRunningError if HTML File is already being updated.
    """
    task_type = 'exec_summary_report'
    task_class = exec_summary_report_csv
    task_input = {}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_course_survey_report(request, course_key):
    """
    Submits a task to generate a HTML File containing the executive summary report.

    Raises AlreadyRunningError if HTML File is already being updated.
    """
    task_type = 'course_survey_report'
    task_class = course_survey_report_csv
    task_input = {}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_proctored_exam_results_report(request, course_key):
    """
    Submits a task to generate a HTML File containing the executive summary report.

    Raises AlreadyRunningError if HTML File is already being updated.
    """
    task_type = 'proctored_exam_results_report'
    task_class = proctored_exam_results_csv
    task_input = {}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_cohort_students(request, course_key, file_name):
    """
    Request to have students cohorted in bulk.

    Raises AlreadyRunningError if students are currently being cohorted.
    """
    task_type = 'cohort_students'
    task_class = cohort_students
    task_input = {'file_name': file_name}
    task_key = ""

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def submit_export_ora2_data(request, course_key):
    """
    AlreadyRunningError is raised if an ora2 report is already being generated.
    """
    task_type = 'export_ora2_data'
    task_class = export_ora2_data
    task_input = {}
    task_key = ''

    return submit_task(request, task_type, task_class, course_key, task_input, task_key)


def generate_certificates_for_students(request, course_key, student_set=None, specific_student_id=None):
    """
    Submits a task to generate certificates for given students enrolled in the course.

     Arguments:
        course_key  : Course Key
        student_set : Semantic for student collection for certificate generation.
                      Options are:
                      'all_whitelisted': All Whitelisted students.
                      'whitelisted_not_generated': Whitelisted students which does not got certificates yet.
                      'specific_student': Single student for certificate generation.
        specific_student_id : Student ID when student_set is 'specific_student'

    Raises AlreadyRunningError if certificates are currently being generated.
    Raises SpecificStudentIdMissingError if student_set is 'specific_student' and specific_student_id is 'None'
    """
    if student_set:
        task_type = 'generate_certificates_student_set'
        task_input = {'student_set': student_set}

        if student_set == 'specific_student':
            task_type = 'generate_certificates_certain_student'
            if specific_student_id is None:
                raise SpecificStudentIdMissingError(
                    "Attempted to generate certificate for a single student, "
                    "but no specific student id provided"
                )
            task_input.update({'specific_student_id': specific_student_id})
    else:
        task_type = 'generate_certificates_all_student'
        task_input = {}

    task_class = generate_certificates
    task_key = ""
    instructor_task = submit_task(request, task_type, task_class, course_key, task_input, task_key)

    CertificateGenerationHistory.objects.create(
        course_id=course_key,
        generated_by=request.user,
        instructor_task=instructor_task,
        is_regeneration=False
    )

    return instructor_task


def regenerate_certificates(request, course_key, statuses_to_regenerate):
    """
    Submits a task to regenerate certificates for given students enrolled in the course.
    Regenerate Certificate only if the status of the existing generated certificate is in 'statuses_to_regenerate'
    list passed in the arguments.

    Raises AlreadyRunningError if certificates are currently being generated.
    """
    task_type = 'regenerate_certificates_all_student'
    task_input = {}

    task_input.update({"statuses_to_regenerate": statuses_to_regenerate})
    task_class = generate_certificates
    task_key = ""

    instructor_task = submit_task(request, task_type, task_class, course_key, task_input, task_key)

    CertificateGenerationHistory.objects.create(
        course_id=course_key,
        generated_by=request.user,
        instructor_task=instructor_task,
        is_regeneration=True
    )

    return instructor_task
