"""
Helpers for the University ID django app, mainly for correct feature checks.
"""

from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.utils import timezone

from courseware.access import has_access
from opaque_keys.edx.locator import UsageKey
from edraak_university.models import UniversityID, UniversityIDSettings
from student.models import CourseEnrollment


def is_feature_enabled():
    """
    Checks if the feature is enabled, useful to avoid writing the feature flag everywhere.
    """
    return settings.FEATURES.get('EDRAAK_UNIVERSITY_APP')


def is_csv_export_enabled_on_course(course):
    """
    Checks if the CSV grade report should include the University ID fields on a given course.
    """
    export_feature_enabled = bool(settings.FEATURES.get('EDRAAK_UNIVERSITY_CSV_EXPORT'))

    return is_feature_enabled() and export_feature_enabled and course.enable_university_id


def get_university_id(user, course_id):
    """
    Gets the University ID (or None) for a user in a course.
    """
    if isinstance(user, AnonymousUser):
        return None

    try:
        return UniversityID.objects.get(
            user=user,
            course_key=course_id,
        )
    except UniversityID.DoesNotExist:
        return None


def show_enroll_banner(user, course_key):
    # This should be in sync with `student/views/views.py:course_info`
    return (
        user.is_authenticated()
        and not CourseEnrollment.is_enrolled(user, course_key)
    )


def is_student_form_disabled(user, course_key):
    """
    This method detects if the form should be disabled or
    enabled. The form is should be disabled in the following cases:
        * If the instructor edited the student data
        * The registration end date (is not null) and (already passed)
        * The user is not enrolled in the course
    :return: True if the form must be disabled, False otherwise
    """
    student_uid = get_university_id(user=user, course_id=course_key)
    if student_uid and not student_uid.can_edit:
        return True

    not_enrolled = not CourseEnrollment.is_enrolled(user=user, course_key=course_key)

    university_settings = get_university_settings(course_key=course_key)
    if university_settings:
        # The instructor already defined a settings for the course
        registration_end = university_settings.registration_end_date
        if registration_end:
            # The registration end date is not stored as null
            today = timezone.now().date()
            return registration_end <= today or not_enrolled

    return not_enrolled


def get_university_settings(course_key):
    try:
        return UniversityIDSettings.objects.get(course_key=course_key)
    except UniversityIDSettings.DoesNotExist:
        return


def has_valid_university_id(user, course_id):
    """
    Returns True if the user has a valid University ID and False otherwise.
    """
    return bool(get_university_id(user, course_id))


def university_id_is_required(user, course):
    """
    Checks if a user is required to enter their University ID and he haven't done that yet.

    Used mainly to determine to block the courseware content before having a valid University ID.
    """
    if not is_feature_enabled():
        return False

    if has_access(user, 'staff', course.id):
        # Skip this test for staff users.
        return False

    if course.enable_university_id:
        if not has_valid_university_id(user, course.id):
            return True

    return False
