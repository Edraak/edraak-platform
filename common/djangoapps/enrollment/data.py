"""
Data Aggregation Layer of the Enrollment API. Collects all enrollment specific data into a single
source to be used throughout the API.
"""
import logging

from django.contrib.auth.models import User
from django.db import transaction
from opaque_keys.edx.keys import CourseKey
from six import text_type

from enrollment.errors import (
    CourseEnrollmentClosedError,
    CourseEnrollmentExistsError,
    CourseEnrollmentFullError,
    InvalidEnrollmentAttribute,
    UserNotFoundError
)
from enrollment.serializers import (
    CourseEnrollmentSerializer,
    CourseSerializer,
    EdraakCourseEnrollmentSerializer
)
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.lib.exceptions import CourseNotFoundError
from student.models import (
    AlreadyEnrolledError,
    CourseEnrollment,
    CourseEnrollmentAttribute,
    CourseFullError,
    EnrollmentClosedError,
    NonExistentCourseError
)

log = logging.getLogger(__name__)


# Edraak: update function to accept request param
def get_course_enrollments(user_id, request=None):
    """Retrieve a list representing all aggregated data for a user's course enrollments.

    Construct a representation of all course enrollment data for a specific user.

    Args:
        user_id (str): The name of the user to retrieve course enrollment information for.
        request: The request that comes with the REST call

    Returns:
        A serializable list of dictionaries of all aggregated enrollment data for a user.

    """
    qset = CourseEnrollment.objects.filter(
        user__username=user_id,
        is_active=True
    ).order_by('created')

    # Edraak: use EdraakCourseEnrollmentSerializer instead of CourseEnrollmentSerializer
    if request is None:
        enrollments = CourseEnrollmentSerializer(
            qset,
            many=True
        ).data
    else:
        enrollments = EdraakCourseEnrollmentSerializer(
            qset,
            many=True,
            context={'request': request}
        ).data

    # Find deleted courses and filter them out of the results
    deleted = []
    valid = []
    for enrollment in enrollments:
        if enrollment.get("course_details") is not None:
            valid.append(enrollment)
        else:
            deleted.append(enrollment)

    if deleted:
        log.warning(
            (
                u"Course enrollments for user %s reference "
                u"courses that do not exist (this can occur if a course is deleted)."
            ), user_id,
        )

    return valid


# Edraak: update function to accept request param
def get_course_enrollment(username, course_id, request=None):
    """Retrieve an object representing all aggregated data for a user's course enrollment.

    Get the course enrollment information for a specific user and course.

    Args:
        username (str): The name of the user to retrieve course enrollment information for.
        course_id (str): The course to retrieve course enrollment information for.
        request: The request that comes with the REST call

    Returns:
        A serializable dictionary representing the course enrollment.

    """
    course_key = CourseKey.from_string(course_id)
    try:
        enrollment = CourseEnrollment.objects.get(
            user__username=username, course_id=course_key
        )

        # Edraak: use EdraakCourseEnrollmentSerializer to serialize enrollments
        if request is None:
            data = CourseEnrollmentSerializer(enrollment).data
        else:
            data = EdraakCourseEnrollmentSerializer(
                enrollment,
                context={'request': request}
            ).data

        return data

    except CourseEnrollment.DoesNotExist:
        return None


def get_user_enrollments(course_key):
    """Based on the course id, return all user enrollments in the course
    Args:
        course_key (CourseKey): Identifier of the course
        from which to retrieve enrollments.
    Returns:
        A course's user enrollments as a queryset
    Raises:
        CourseEnrollment.DoesNotExist
    """
    return CourseEnrollment.objects.filter(
        course_id=course_key,
        is_active=True
    ).order_by('created')


# Edraak: update function to accept request param
def create_course_enrollment(username, course_id, mode, is_active, request=None):
    """Create a new course enrollment for the given user.

    Creates a new course enrollment for the specified user username.

    Args:
        username (str): The name of the user to create a new course enrollment for.
        course_id (str): The course to create the course enrollment for.
        mode (str): (Optional) The mode for the new enrollment.
        is_active (boolean): (Optional) Determines if the enrollment is active.
        request: The request that comes with the REST call

    Returns:
        A serializable dictionary representing the new course enrollment.

    Raises:
        CourseNotFoundError
        CourseEnrollmentFullError
        EnrollmentClosedError
        CourseEnrollmentExistsError

    """
    course_key = CourseKey.from_string(course_id)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        msg = u"Not user with username '{username}' found.".format(username=username)
        log.warn(msg)
        raise UserNotFoundError(msg)

    try:
        enrollment = CourseEnrollment.enroll(user, course_key, check_access=True)
        return _update_enrollment(enrollment, is_active=is_active, mode=mode)
    except NonExistentCourseError as err:
        raise CourseNotFoundError(text_type(err))
    except EnrollmentClosedError as err:
        raise CourseEnrollmentClosedError(text_type(err))
    except CourseFullError as err:
        raise CourseEnrollmentFullError(text_type(err))
    except AlreadyEnrolledError as err:
        # Edraak: pass request param to get_course_enrollment
        enrollment = get_course_enrollment(username, course_id, request=request)
        raise CourseEnrollmentExistsError(text_type(err), enrollment)


def update_course_enrollment(username, course_id, mode=None, is_active=None):
    """Modify a course enrollment for a user.

    Allows updates to a specific course enrollment.

    Args:
        username (str): The name of the user to retrieve course enrollment information for.
        course_id (str): The course to retrieve course enrollment information for.
        mode (str): (Optional) If specified, modify the mode for this enrollment.
        is_active (boolean): (Optional) Determines if the enrollment is active.

    Returns:
        A serializable dictionary representing the modified course enrollment.

    """
    course_key = CourseKey.from_string(course_id)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        msg = u"Not user with username '{username}' found.".format(username=username)
        log.warn(msg)
        raise UserNotFoundError(msg)

    try:
        enrollment = CourseEnrollment.objects.get(user=user, course_id=course_key)
        return _update_enrollment(enrollment, is_active=is_active, mode=mode)
    except CourseEnrollment.DoesNotExist:
        return None


def add_or_update_enrollment_attr(user_id, course_id, attributes):
    """Set enrollment attributes for the enrollment of given user in the
    course provided.

    Args:
        course_id (str): The Course to set enrollment attributes for.
        user_id (str): The User to set enrollment attributes for.
        attributes (list): Attributes to be set.

    Example:
        >>>add_or_update_enrollment_attr(
            "Bob",
            "course-v1-edX-DemoX-1T2015",
            [
                {
                    "namespace": "credit",
                    "name": "provider_id",
                    "value": "hogwarts",
                },
            ]
        )
    """
    course_key = CourseKey.from_string(course_id)
    user = _get_user(user_id)
    enrollment = CourseEnrollment.get_enrollment(user, course_key)
    if not _invalid_attribute(attributes) and enrollment is not None:
        CourseEnrollmentAttribute.add_enrollment_attr(enrollment, attributes)


def get_enrollment_attributes(user_id, course_id):
    """Retrieve enrollment attributes for given user for provided course.

    Args:
        user_id: The User to get enrollment attributes for
        course_id (str): The Course to get enrollment attributes for.

    Example:
        >>>get_enrollment_attributes("Bob", "course-v1-edX-DemoX-1T2015")
        [
            {
                "namespace": "credit",
                "name": "provider_id",
                "value": "hogwarts",
            },
        ]

    Returns: list
    """
    course_key = CourseKey.from_string(course_id)
    user = _get_user(user_id)
    enrollment = CourseEnrollment.get_enrollment(user, course_key)
    return CourseEnrollmentAttribute.get_enrollment_attributes(enrollment)


def unenroll_user_from_all_courses(user_id):
    """
    Set all of a user's enrollments to inactive.
    :param user_id: The user being unenrolled.
    :return: A list of all courses from which the user was unenrolled.
    """
    user = _get_user(user_id)
    enrollments = CourseEnrollment.objects.filter(user=user)
    with transaction.atomic():
        for enrollment in enrollments:
            _update_enrollment(enrollment, is_active=False)

    return set([str(enrollment.course_id.org) for enrollment in enrollments])


def _get_user(user_id):
    """Retrieve user with provided user_id

    Args:
        user_id(str): username of the user for which object is to retrieve

    Returns: obj
    """
    try:
        return User.objects.get(username=user_id)
    except User.DoesNotExist:
        msg = u"Not user with username '{username}' found.".format(username=user_id)
        log.warn(msg)
        raise UserNotFoundError(msg)


def _update_enrollment(enrollment, is_active=None, mode=None):
    enrollment.update_enrollment(is_active=is_active, mode=mode)
    enrollment.save()
    return CourseEnrollmentSerializer(enrollment).data


def _invalid_attribute(attributes):
    """Validate enrollment attribute

    Args:
        attributes(dict): dict of attribute

    Return:
        list of invalid attributes
    """
    invalid_attributes = []
    for attribute in attributes:
        if "namespace" not in attribute:
            msg = u"'namespace' not in enrollment attribute"
            log.warn(msg)
            invalid_attributes.append("namespace")
            raise InvalidEnrollmentAttribute(msg)
        if "name" not in attribute:
            msg = u"'name' not in enrollment attribute"
            log.warn(msg)
            invalid_attributes.append("name")
            raise InvalidEnrollmentAttribute(msg)
        if "value" not in attribute:
            msg = u"'value' not in enrollment attribute"
            log.warn(msg)
            invalid_attributes.append("value")
            raise InvalidEnrollmentAttribute(msg)

    return invalid_attributes


def get_course_enrollment_info(course_id, include_expired=False):
    """Returns all course enrollment information for the given course.

    Based on the course id, return all related course information.

    Args:
        course_id (str): The course to retrieve enrollment information for.

        include_expired (bool): Boolean denoting whether expired course modes
        should be included in the returned JSON data.

    Returns:
        A serializable dictionary representing the course's enrollment information.

    Raises:
        CourseNotFoundError

    """
    course_key = CourseKey.from_string(course_id)

    try:
        course = CourseOverview.get_from_id(course_key)
    except CourseOverview.DoesNotExist:
        msg = u"Requested enrollment information for unknown course {course}".format(course=course_id)
        log.warning(msg)
        raise CourseNotFoundError(msg)
    else:
        return CourseSerializer(course, include_expired=include_expired).data
