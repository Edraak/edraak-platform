"""
Helpers for the University ID django app, mainly for correct feature checks.
"""

from django.contrib.auth.models import AnonymousUser
from django.conf import settings

from opaque_keys.edx.locator import CourseLocator

from edraak_university.models import UniversityID


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
            course_key=CourseLocator.from_string(course_id),
        )
    except UniversityID.DoesNotExist:
        return None


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

    if course.enable_university_id:
        if not has_valid_university_id(user, unicode(course.id)):
            return True

    return False
