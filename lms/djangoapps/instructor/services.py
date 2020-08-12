"""
Implementation of "Instructor" service
"""

import logging

from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import ugettext as _
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey, UsageKey

import lms.djangoapps.instructor.enrollment as enrollment
from courseware.models import StudentModule
from lms.djangoapps.commerce.utils import create_zendesk_ticket
from lms.djangoapps.instructor.views.tools import get_student_from_identifier
from student import auth
from student.roles import CourseStaffRole
from xmodule.modulestore.django import modulestore

log = logging.getLogger(__name__)


class InstructorService(object):
    """
    Instructor service for deleting the students attempt(s) of an exam. This service has been created
    for the edx_proctoring's dependency injection to cater for a requirement where edx_proctoring
    needs to call into edx-platform's functions to delete the students' existing answers, grades
    and attempt counts if there had been an earlier attempt.
    """

    def delete_student_attempt(self, student_identifier, course_id, content_id, requesting_user):
        """
        Deletes student state for a problem. requesting_user may be kept as an audit trail.

        Takes some of the following query parameters
            - student_identifier is an email or username
            - content_id is a url-name of a problem
            - course_id is the id for the course
        """
        course_id = CourseKey.from_string(course_id)

        try:
            student = get_student_from_identifier(student_identifier)
        except ObjectDoesNotExist:
            err_msg = (
                'Error occurred while attempting to reset student attempts for user '
                '{student_identifier} for content_id {content_id}. '
                'User does not exist!'.format(
                    student_identifier=student_identifier,
                    content_id=content_id
                )
            )
            log.error(err_msg)
            return

        try:
            module_state_key = UsageKey.from_string(content_id)
        except InvalidKeyError:
            err_msg = (
                'Invalid content_id {content_id}!'.format(content_id=content_id)
            )
            log.error(err_msg)
            return

        if student:
            try:
                enrollment.reset_student_attempts(
                    course_id,
                    student,
                    module_state_key,
                    requesting_user=requesting_user,
                    delete_module=True,
                )
            except (StudentModule.DoesNotExist, enrollment.sub_api.SubmissionError):
                err_msg = (
                    'Error occurred while attempting to reset student attempts for user '
                    '{student_identifier} for content_id {content_id}.'.format(
                        student_identifier=student_identifier,
                        content_id=content_id
                    )
                )
                log.error(err_msg)

    def is_course_staff(self, user, course_id):
        """
        Returns True if the user is the course staff
        else Returns False
        """
        return auth.user_has_role(user, CourseStaffRole(CourseKey.from_string(course_id)))

    def send_support_notification(self, course_id, exam_name, student_username, review_status, review_url=None):
        """
        Creates a Zendesk ticket for an exam attempt review from the proctoring system.
        Currently, it sends notifications for 'Suspicious" status, but additional statuses can be supported
        by adding to the notify_support_for_status list in edx_proctoring/backends/software_secure.py
        The notifications can be disabled by disabling the
        "Create Zendesk Tickets For Suspicious Proctored Exam Attempts" setting in the course's Advanced settings.
        """

        course_key = CourseKey.from_string(course_id)
        course = modulestore().get_course(course_key)

        if course.create_zendesk_tickets:
            requester_name = "edx-proctoring"
            email = "edx-proctoring@edx.org"
            subject = _(u"Proctored Exam Review: {review_status}").format(review_status=review_status)
            body = _(
                u"A proctored exam attempt for {exam_name} in {course_name} by username: {student_username} "
                "was reviewed as {review_status} by the proctored exam review provider.\n"
                "Review link: {review_url}"
            ).format(
                exam_name=exam_name,
                course_name=course.display_name,
                student_username=student_username,
                review_status=review_status,
                review_url=review_url or u'not available',
            )
            tags = ["proctoring"]
            create_zendesk_ticket(requester_name, email, subject, body, tags)
