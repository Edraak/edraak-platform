"""
The public API for certificates.
"""
import logging
from datetime import datetime

from pytz import UTC

from lms.djangoapps.certificates.models import CertificateWhitelist
from openedx.core.djangoapps.certificates.config import waffle
from student.models import CourseEnrollment

log = logging.getLogger(__name__)

SWITCHES = waffle.waffle()


def auto_certificate_generation_enabled():
    return SWITCHES.is_enabled(waffle.AUTO_CERTIFICATE_GENERATION)


def _enabled_and_instructor_paced(course):
    if auto_certificate_generation_enabled():
        return not course.self_paced
    return False


def certificates_viewable_for_course(course):
    """
    Returns True if certificates are viewable for any student enrolled in the course, False otherwise.
    """
    if course.self_paced:
        return True
    if (
        course.certificates_display_behavior in ('early_with_info', 'early_no_info')
        or course.certificates_show_before_end
    ):
        return True
    if (
        course.certificate_available_date
        and course.certificate_available_date <= datetime.now(UTC)
    ):
        return True
    if (
        course.certificate_available_date is None
        and course.has_ended()
    ):
        return True
    return False


def is_certificate_valid(certificate):
    """
    Returns True if the student has a valid, verified certificate for this course, False otherwise.
    """
    return CourseEnrollment.is_enrolled_as_verified(certificate.user, certificate.course_id) and certificate.is_valid()


def can_show_certificate_message(course, student, course_grade, certificates_enabled_for_course):
    is_whitelisted = CertificateWhitelist.objects.filter(user=student, course_id=course.id, whitelist=True).exists()
    auto_cert_gen_enabled = auto_certificate_generation_enabled()
    has_active_enrollment = CourseEnrollment.is_enrolled(student, course.id)
    certificates_are_viewable = certificates_viewable_for_course(course)

    # Adding a temporary logging for EDUCATOR-2017.
    if unicode(course.id) == u'course-v1:RITx+PM9004x+3T2017':
        log.info(
            (
                u'can_show_certificate_message called with:'
                u'course:%s, student: %s, course grade: %s,'
                u'certificates_enabled_for_course: %s, certificates_viewable_for_course: %s, auto_cert_gen_enabled: %s,'
                u'has_active_enrollment: %s, passed: %s, is_whitelisted: %s'
            ),
            course.id,
            student.username,
            course_grade,
            certificates_enabled_for_course,
            certificates_are_viewable,
            auto_cert_gen_enabled,
            has_active_enrollment,
            course_grade.passed,
            is_whitelisted
        )
    if not (
        (auto_cert_gen_enabled or certificates_enabled_for_course) and
        has_active_enrollment and
        certificates_are_viewable and
        (course_grade.passed or is_whitelisted)
    ):
        return False
    return True


def can_show_certificate_available_date_field(course):
    return _enabled_and_instructor_paced(course)


def _course_uses_available_date(course):
    return can_show_certificate_available_date_field(course) and course.certificate_available_date


def available_date_for_certificate(course, certificate):
    if _course_uses_available_date(course):
        return course.certificate_available_date
    return certificate.modified_date


def display_date_for_certificate(course, certificate):
    if _course_uses_available_date(course) and course.certificate_available_date < datetime.now(UTC):
        return course.certificate_available_date
    return certificate.modified_date
