"""
This file contains (or should), all access control logic for the courseware.
Ideally, it will be the only place that needs to know about any special settings
like DISABLE_START_DATES.

Note: The access control logic in this file does NOT check for enrollment in
  a course.  It is expected that higher layers check for enrollment so we
  don't have to hit the enrollments table on every module load.

  If enrollment is to be checked, use get_course_with_access in courseware.courses.
  It is a wrapper around has_access that additionally checks for enrollment.
"""
import logging
from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from pytz import UTC
from opaque_keys.edx.keys import CourseKey, UsageKey
from six import text_type
from xblock.core import XBlock

from courseware.access_response import (
    MilestoneAccessError,
    MobileAvailabilityError,
    VisibilityError,
)
from courseware.access_utils import (
    ACCESS_DENIED,
    ACCESS_GRANTED,
    adjust_start_date,
    check_start_date,
    debug,
    in_preview_mode,
    check_course_open_for_learner,
)
from courseware.access_response import (
    NoAllowedPartitionGroupsError,
    IncorrectPartitionGroupError,
)
from courseware.masquerade import get_masquerade_role, is_masquerading_as_student
from lms.djangoapps.ccx.custom_exception import CCXLocatorValidationException
from lms.djangoapps.ccx.models import CustomCourseForEdX
from mobile_api.models import IgnoreMobileAvailableFlagConfig
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.external_auth.models import ExternalAuthMap
from openedx.features.course_duration_limits.access import check_course_expired
from student import auth
from student.models import CourseEnrollmentAllowed
from student.roles import (
    CourseBetaTesterRole,
    CourseCcxCoachRole,
    CourseInstructorRole,
    CourseStaffRole,
    GlobalStaff,
    OrgInstructorRole,
    OrgStaffRole,
    SupportStaffRole
)
from util import milestones_helpers as milestones_helpers
from util.milestones_helpers import (
    any_unfulfilled_milestones,
    get_pre_requisite_courses_not_completed,
    is_prerequisite_courses_enabled
)
from xmodule.course_module import CATALOG_VISIBILITY_ABOUT, CATALOG_VISIBILITY_CATALOG_AND_ABOUT, CourseDescriptor
from xmodule.error_module import ErrorDescriptor
from xmodule.partitions.partitions import NoSuchUserPartitionError, NoSuchUserPartitionGroupError
from xmodule.x_module import XModule

log = logging.getLogger(__name__)


def has_ccx_coach_role(user, course_key):
    """
    Check if user is a coach on this ccx.

    Arguments:
        user (User): the user whose descriptor access we are checking.
        course_key (CCXLocator): Key to CCX.

    Returns:
        bool: whether user is a coach on this ccx or not.
    """
    if hasattr(course_key, 'ccx'):
        ccx_id = course_key.ccx
        role = CourseCcxCoachRole(course_key)

        if role.has_user(user):
            list_ccx = CustomCourseForEdX.objects.filter(
                course_id=course_key.to_course_locator(),
                coach=user
            )
            if list_ccx.exists():
                coach_ccx = list_ccx[0]
                return str(coach_ccx.id) == ccx_id
    else:
        raise CCXLocatorValidationException("Invalid CCX key. To verify that "
                                            "user is a coach on CCX, you must provide key to CCX")
    return False


def has_access(user, action, obj, course_key=None):
    """
    Check whether a user has the access to do action on obj.  Handles any magic
    switching based on various settings.

    Things this module understands:
    - start dates for modules
    - visible_to_staff_only for modules
    - DISABLE_START_DATES
    - different access for instructor, staff, course staff, and students.
    - mobile_available flag for course modules

    user: a Django user object. May be anonymous. If none is passed,
                    anonymous is assumed

    obj: The object to check access for.  A module, descriptor, location, or
                    certain special strings (e.g. 'global')

    action: A string specifying the action that the client is trying to perform.

    actions depend on the obj type, but include e.g. 'enroll' for courses.  See the
    type-specific functions below for the known actions for that type.

    course_key: A course_key specifying which course run this access is for.
        Required when accessing anything other than a CourseDescriptor, 'global',
        or a location with category 'course'

    Returns an AccessResponse object.  It is up to the caller to actually
    deny access in a way that makes sense in context.
    """
    # Just in case user is passed in as None, make them anonymous
    if not user:
        user = AnonymousUser()

    # Preview mode is only accessible by staff.
    if in_preview_mode() and course_key:
        if not has_staff_access_to_preview_mode(user, course_key):
            return ACCESS_DENIED

    # delegate the work to type-specific functions.
    # (start with more specific types, then get more general)
    if isinstance(obj, CourseDescriptor):
        return _has_access_course(user, action, obj)

    if isinstance(obj, CourseOverview):
        return _has_access_course(user, action, obj)

    if isinstance(obj, ErrorDescriptor):
        return _has_access_error_desc(user, action, obj, course_key)

    if isinstance(obj, XModule):
        return _has_access_xmodule(user, action, obj, course_key)

    # NOTE: any descriptor access checkers need to go above this
    if isinstance(obj, XBlock):
        return _has_access_descriptor(user, action, obj, course_key)

    if isinstance(obj, CourseKey):
        return _has_access_course_key(user, action, obj)

    if isinstance(obj, UsageKey):
        return _has_access_location(user, action, obj, course_key)

    if isinstance(obj, basestring):
        return _has_access_string(user, action, obj)

    # Passing an unknown object here is a coding error, so rather than
    # returning a default, complain.
    raise TypeError("Unknown object type in has_access(): '{0}'"
                    .format(type(obj)))


def has_staff_access_to_preview_mode(user, course_key):
    """
    Checks if given user can access course in preview mode.
    A user can access a course in preview mode only if User has staff access to course.
    """
    has_admin_access_to_course = any(administrative_accesses_to_course_for_user(user, course_key))

    return has_admin_access_to_course or is_masquerading_as_student(user, course_key)


def _can_view_courseware_with_prerequisites(user, course):
    """
    Checks if a user has access to a course based on its prerequisites.

    If the user is staff or anonymous, immediately grant access.
    Else, return whether or not the prerequisite courses have been passed.

    Arguments:
        user (User): the user whose course access we are checking.
        course (AType): the course for which we are checking access.
            where AType is CourseDescriptor, CourseOverview, or any other
            class that represents a course and has the attributes .location
            and .id.
    """

    def _is_prerequisites_disabled():
        """
        Checks if prerequisites are disabled in the settings.
        """
        return ACCESS_DENIED if is_prerequisite_courses_enabled() else ACCESS_GRANTED

    return (
        _is_prerequisites_disabled()
        or _has_staff_access_to_descriptor(user, course, course.id)
        or user.is_anonymous
        or _has_fulfilled_prerequisites(user, [course.id])
    )


def _can_load_course_on_mobile(user, course):
    """
    Checks if a user can view the given course on a mobile device.

    This function only checks mobile-specific access restrictions. Other access
    restrictions such as start date and the .visible_to_staff_only flag must
    be checked by callers in *addition* to the return value of this function.

    Arguments:
        user (User): the user whose course access we are checking.
        course (CourseDescriptor|CourseOverview): the course for which we are
            checking access.

    Returns:
        bool: whether the course can be accessed on mobile.
    """
    return (
        is_mobile_available_for_user(user, course) and
        (
            _has_staff_access_to_descriptor(user, course, course.id) or
            _has_fulfilled_all_milestones(user, course.id)
        )
    )


def _can_enroll_courselike(user, courselike):
    """
    Ascertain if the user can enroll in the given courselike object.

    Arguments:
        user (User): The user attempting to enroll.
        courselike (CourseDescriptor or CourseOverview): The object representing the
            course in which the user is trying to enroll.

    Returns:
        AccessResponse, indicating whether the user can enroll.
    """
    enrollment_domain = courselike.enrollment_domain
    # Courselike objects (e.g., course descriptors and CourseOverviews) have an attribute named `id`
    # which actually points to a CourseKey. Sigh.
    course_key = courselike.id

    # If using a registration method to restrict enrollment (e.g., Shibboleth)
    if settings.FEATURES.get('RESTRICT_ENROLL_BY_REG_METHOD') and enrollment_domain:
        if user is not None and user.is_authenticated and \
                ExternalAuthMap.objects.filter(user=user, external_domain=enrollment_domain):
            debug("Allow: external_auth of " + enrollment_domain)
            reg_method_ok = True
        else:
            reg_method_ok = False
    else:
        reg_method_ok = True

    # If the user appears in CourseEnrollmentAllowed paired with the given course key,
    # they may enroll, except if the CEA has already been used by a different user.
    # Note that as dictated by the legacy database schema, the filter call includes
    # a `course_id` kwarg which requires a CourseKey.
    if user is not None and user.is_authenticated:
        cea = CourseEnrollmentAllowed.objects.filter(email=user.email, course_id=course_key).first()
        if cea and cea.valid_for_user(user):
            return ACCESS_GRANTED
        elif cea:
            debug("Deny: CEA was already consumed by a different user {} and can't be used again by {}".format(
                cea.user.id,
                user.id,
            ))
            return ACCESS_DENIED

    if _has_staff_access_to_descriptor(user, courselike, course_key):
        return ACCESS_GRANTED

    if courselike.invitation_only:
        debug("Deny: invitation only")
        return ACCESS_DENIED

    now = datetime.now(UTC)
    enrollment_start = courselike.enrollment_start or datetime.min.replace(tzinfo=UTC)
    enrollment_end = courselike.enrollment_end or datetime.max.replace(tzinfo=UTC)
    if reg_method_ok and enrollment_start < now < enrollment_end:
        debug("Allow: in enrollment period")
        return ACCESS_GRANTED

    return ACCESS_DENIED


def _has_access_course(user, action, courselike):
    """
    Check if user has access to a course.

    Arguments:
        user (User): the user whose course access we are checking.
        action (string): The action that is being checked.
        courselike (CourseDescriptor or CourseOverview): The object
            representing the course that the user wants to access.

    Valid actions:

    'load' -- load the courseware, see inside the course
    'load_forum' -- can load and contribute to the forums (one access level for now)
    'load_mobile' -- can load from a mobile context
    'enroll' -- enroll.  Checks for enrollment window.
    'see_exists' -- can see that the course exists.
    'staff' -- staff access to course.
    'see_in_catalog' -- user is able to see the course listed in the course catalog.
    'see_about_page' -- user is able to see the course about page.
    """
    def can_load():
        """
        Can this user load this course?

        NOTE: this is not checking whether user is actually enrolled in the course.
        """
        # N.B. I'd love a better way to handle this pattern, without breaking the
        # shortcircuiting logic. Maybe AccessResponse needs to grow a
        # fluent interface?
        #
        # return (
        #     _visible_to_nonstaff_users(courselike).and(
        #         check_course_open_for_learner, user, courselike
        #     ).and(
        #         _can_view_courseware_with_prerequisites, user, courselike
        #     )
        # ).or(
        #     _has_staff_access_to_descriptor, user, courselike, courselike.id
        # )
        visible_to_nonstaff = _visible_to_nonstaff_users(courselike)
        if not visible_to_nonstaff:
            staff_access = _has_staff_access_to_descriptor(user, courselike, courselike.id)
            if staff_access:
                return staff_access
            else:
                return visible_to_nonstaff

        open_for_learner = check_course_open_for_learner(user, courselike)
        if not open_for_learner:
            staff_access = _has_staff_access_to_descriptor(user, courselike, courselike.id)
            if staff_access:
                return staff_access
            else:
                return open_for_learner

        view_with_prereqs = _can_view_courseware_with_prerequisites(user, courselike)
        if not view_with_prereqs:
            staff_access = _has_staff_access_to_descriptor(user, courselike, courselike.id)
            if staff_access:
                return staff_access
            else:
                return view_with_prereqs

        has_not_expired = check_course_expired(user, courselike)
        if not has_not_expired:
            staff_access = _has_staff_access_to_descriptor(user, courselike, courselike.id)
            if staff_access:
                return staff_access
            else:
                return has_not_expired

        return ACCESS_GRANTED

    def can_enroll():
        """
        Returns whether the user can enroll in the course.
        """
        return _can_enroll_courselike(user, courselike)

    def see_exists():
        """
        Can see if can enroll, but also if can load it: if user enrolled in a course and now
        it's past the enrollment period, they should still see it.
        """
        return ACCESS_GRANTED if (can_load() or can_enroll()) else ACCESS_DENIED

    def can_see_in_catalog():
        """
        Implements the "can see course in catalog" logic if a course should be visible in the main course catalog
        In this case we use the catalog_visibility property on the course descriptor
        but also allow course staff to see this.
        """
        return (
            _has_catalog_visibility(courselike, CATALOG_VISIBILITY_CATALOG_AND_ABOUT)
            or _has_staff_access_to_descriptor(user, courselike, courselike.id)
        )

    def can_see_about_page():
        """
        Implements the "can see course about page" logic if a course about page should be visible
        In this case we use the catalog_visibility property on the course descriptor
        but also allow course staff to see this.
        """
        return (
            _has_catalog_visibility(courselike, CATALOG_VISIBILITY_CATALOG_AND_ABOUT)
            or _has_catalog_visibility(courselike, CATALOG_VISIBILITY_ABOUT)
            or _has_staff_access_to_descriptor(user, courselike, courselike.id)
        )

    checkers = {
        'load': can_load,
        'load_mobile': lambda: can_load() and _can_load_course_on_mobile(user, courselike),
        'enroll': can_enroll,
        'see_exists': see_exists,
        'staff': lambda: _has_staff_access_to_descriptor(user, courselike, courselike.id),
        'instructor': lambda: _has_instructor_access_to_descriptor(user, courselike, courselike.id),
        'see_in_catalog': can_see_in_catalog,
        'see_about_page': can_see_about_page,
    }

    return _dispatch(checkers, action, user, courselike)


def _has_access_error_desc(user, action, descriptor, course_key):
    """
    Only staff should see error descriptors.

    Valid actions:
    'load' -- load this descriptor, showing it to the user.
    'staff' -- staff access to descriptor.
    """
    def check_for_staff():
        return _has_staff_access_to_descriptor(user, descriptor, course_key)

    checkers = {
        'load': check_for_staff,
        'staff': check_for_staff,
        'instructor': lambda: _has_instructor_access_to_descriptor(user, descriptor, course_key)
    }

    return _dispatch(checkers, action, user, descriptor)


def _has_group_access(descriptor, user, course_key):
    """
    This function returns a boolean indicating whether or not `user` has
    sufficient group memberships to "load" a block (the `descriptor`)
    """
    # Allow staff and instructors roles group access, as they are not masquerading as a student.
    if get_user_role(user, course_key) in ['staff', 'instructor']:
        return ACCESS_GRANTED

    # use merged_group_access which takes group access on the block's
    # parents / ancestors into account
    merged_access = descriptor.merged_group_access

    # resolve the partition IDs in group_access to actual
    # partition objects, skipping those which contain empty group directives.
    # If a referenced partition could not be found, it will be denied
    # If the partition is found but is no longer active (meaning it's been disabled)
    # then skip the access check for that partition.
    partitions = []
    for partition_id, group_ids in merged_access.items():
        try:
            partition = descriptor._get_user_partition(partition_id)  # pylint: disable=protected-access

            # check for False in merged_access, which indicates that at least one
            # partition's group list excludes all students.
            if group_ids is False:
                log.warning("Group access check excludes all students, access will be denied.", exc_info=True)
                return NoAllowedPartitionGroupsError(partition)

            if partition.active:
                if group_ids is not None:
                    partitions.append(partition)
            else:
                log.debug(
                    "Skipping partition with ID %s in course %s because it is no longer active",
                    partition.id, course_key
                )
        except NoSuchUserPartitionError:
            log.warning("Error looking up user partition, access will be denied.", exc_info=True)
            return ACCESS_DENIED

    # next resolve the group IDs specified within each partition
    partition_groups = []
    try:
        for partition in partitions:
            groups = [
                partition.get_group(group_id)
                for group_id in merged_access[partition.id]
            ]
            if groups:
                partition_groups.append((partition, groups))
    except NoSuchUserPartitionGroupError:
        log.warning("Error looking up referenced user partition group, access will be denied.", exc_info=True)
        return ACCESS_DENIED

    # finally: check that the user has a satisfactory group assignment
    # for each partition.

    # missing_groups is the list of groups that the user is NOT in but would NEED to be in order to be granted access.
    # For each partition there are group(s) of users that are granted access to this content.
    # Below, we loop through each partition and check if the user belongs to one of the appropriate group(s). If they do
    # not that group is added to their list of missing_groups.
    # If missing_groups is empty, the user is granted access.
    # If missing_groups is NOT empty, we generate an error based on one of the particular groups they are missing.
    missing_groups = []
    for partition, groups in partition_groups:
        user_group = partition.scheme.get_group_for_user(
            course_key,
            user,
            partition,
        )
        if user_group not in groups:
            missing_groups.append((partition, user_group, groups))

    if missing_groups:
        partition, user_group, allowed_groups = missing_groups[0]
        return IncorrectPartitionGroupError(
            partition=partition,
            user_group=user_group,
            allowed_groups=allowed_groups,
            user_message=partition.access_denied_message(descriptor, user, user_group, allowed_groups),
            user_fragment=partition.access_denied_fragment(descriptor, user, user_group, allowed_groups),
        )

    # all checks passed.
    return ACCESS_GRANTED


def _has_access_descriptor(user, action, descriptor, course_key=None):
    """
    Check if user has access to this descriptor.

    Valid actions:
    'load' -- load this descriptor, showing it to the user.
    'staff' -- staff access to descriptor.

    NOTE: This is the fallback logic for descriptors that don't have custom policy
    (e.g. courses).  If you call this method directly instead of going through
    has_access(), it will not do the right thing.
    """
    def can_load():
        """
        NOTE: This does not check that the student is enrolled in the course
        that contains this module.  We may or may not want to allow non-enrolled
        students to see modules.  If not, views should check the course, so we
        don't have to hit the enrollments table on every module load.
        """
        # If the user (or the role the user is currently masquerading as) does not have
        # access to this content, then deny access. The problem with calling _has_staff_access_to_descriptor
        # before this method is that _has_staff_access_to_descriptor short-circuits and returns True
        # for staff users in preview mode.
        group_access_response = _has_group_access(descriptor, user, course_key)
        if not group_access_response:
            return group_access_response

        # If the user has staff access, they can load the module and checks below are not needed.
        staff_access_response = _has_staff_access_to_descriptor(user, descriptor, course_key)
        if staff_access_response:
            return staff_access_response

        return (
            _visible_to_nonstaff_users(descriptor) and
            (
                _has_detached_class_tag(descriptor) or
                check_start_date(user, descriptor.days_early_for_beta, descriptor.start, course_key)
            )
        )

    checkers = {
        'load': can_load,
        'staff': lambda: _has_staff_access_to_descriptor(user, descriptor, course_key),
        'instructor': lambda: _has_instructor_access_to_descriptor(user, descriptor, course_key)
    }

    return _dispatch(checkers, action, user, descriptor)


def _has_access_xmodule(user, action, xmodule, course_key):
    """
    Check if user has access to this xmodule.

    Valid actions:
      - same as the valid actions for xmodule.descriptor
    """
    # Delegate to the descriptor
    return has_access(user, action, xmodule.descriptor, course_key)


def _has_access_location(user, action, location, course_key):
    """
    Check if user has access to this location.

    Valid actions:
    'staff' : True if the user has staff access to this location

    NOTE: if you add other actions, make sure that

     has_access(user, location, action) == has_access(user, get_item(location), action)
    """
    checkers = {
        'staff': lambda: _has_staff_access_to_location(user, location, course_key)
    }

    return _dispatch(checkers, action, user, location)


def _has_access_course_key(user, action, course_key):
    """
    Check if user has access to the course with this course_key

    Valid actions:
    'staff' : True if the user has staff access to this location
    'instructor' : True if the user has staff access to this location
    """
    checkers = {
        'staff': lambda: _has_staff_access_to_location(user, None, course_key),
        'instructor': lambda: _has_instructor_access_to_location(user, None, course_key),
    }

    return _dispatch(checkers, action, user, course_key)


def _has_access_string(user, action, perm):
    """
    Check if user has certain special access, specified as string.  Valid strings:

    'global'

    Valid actions:

    'staff' -- global staff access.
    'support' -- access to student support functionality
    'certificates' --- access to view and regenerate certificates for other users.
    """

    def check_staff():
        """
        Checks for staff access
        """
        if perm != 'global':
            debug("Deny: invalid permission '%s'", perm)
            return ACCESS_DENIED
        return ACCESS_GRANTED if GlobalStaff().has_user(user) else ACCESS_DENIED

    def check_support():
        """Check that the user has access to the support UI. """
        if perm != 'global':
            return ACCESS_DENIED
        return (
            ACCESS_GRANTED if GlobalStaff().has_user(user) or SupportStaffRole().has_user(user)
            else ACCESS_DENIED
        )

    checkers = {
        'staff': check_staff,
        'support': check_support,
        'certificates': check_support,
    }

    return _dispatch(checkers, action, user, perm)


#####  Internal helper methods below

def _dispatch(table, action, user, obj):
    """
    Helper: call table[action], raising a nice pretty error if there is no such key.

    user and object passed in only for error messages and debugging
    """
    if action in table:
        result = table[action]()
        debug("%s user %s, object %s, action %s",
              'ALLOWED' if result else 'DENIED',
              user,
              text_type(obj.location) if isinstance(obj, XBlock) else str(obj),
              action)
        return result

    raise ValueError(u"Unknown action for object type '{0}': '{1}'".format(
        type(obj), action))


def _adjust_start_date_for_beta_testers(user, descriptor, course_key):
    """
    If user is in a beta test group, adjust the start date by the appropriate number of
    days.

    Arguments:
       user: A django user.  May be anonymous.
       descriptor: the XModuleDescriptor the user is trying to get access to, with a
       non-None start date.

    Returns:
        A datetime.  Either the same as start, or earlier for beta testers.

    NOTE: number of days to adjust should be cached to avoid looking it up thousands of
    times per query.

    NOTE: For now, this function assumes that the descriptor's location is in the course
    the user is looking at.  Once we have proper usages and definitions per the XBlock
    design, this should use the course the usage is in.
    """
    return adjust_start_date(user, descriptor.days_early_for_beta, descriptor.start, course_key)


def _has_instructor_access_to_location(user, location, course_key=None):
    if course_key is None:
        course_key = location.course_key
    return _has_access_to_course(user, 'instructor', course_key)


def _has_staff_access_to_location(user, location, course_key=None):
    if course_key is None:
        course_key = location.course_key
    return _has_access_to_course(user, 'staff', course_key)


def _has_access_to_course(user, access_level, course_key):
    """
    Returns True if the given user has access_level (= staff or
    instructor) access to the course with the given course_key.
    This ensures the user is authenticated and checks if global staff or has
    staff / instructor access.

    access_level = string, either "staff" or "instructor"
    """
    if user is None or (not user.is_authenticated):
        debug("Deny: no user or anon user")
        return ACCESS_DENIED

    if is_masquerading_as_student(user, course_key):
        return ACCESS_DENIED

    global_staff, staff_access, instructor_access = administrative_accesses_to_course_for_user(user, course_key)

    if global_staff:
        debug("Allow: user.is_staff")
        return ACCESS_GRANTED

    if access_level not in ('staff', 'instructor'):
        log.debug("Error in access._has_access_to_course access_level=%s unknown", access_level)
        debug("Deny: unknown access level")
        return ACCESS_DENIED

    if staff_access and access_level == 'staff':
        debug("Allow: user has course staff access")
        return ACCESS_GRANTED

    if instructor_access and access_level in ('staff', 'instructor'):
        debug("Allow: user has course instructor access")
        return ACCESS_GRANTED

    debug("Deny: user did not have correct access")
    return ACCESS_DENIED


def administrative_accesses_to_course_for_user(user, course_key):
    """
    Returns types of access a user have for given course.
    """
    global_staff = GlobalStaff().has_user(user)

    staff_access = (
        CourseStaffRole(course_key).has_user(user) or
        OrgStaffRole(course_key.org).has_user(user)
    )

    instructor_access = (
        CourseInstructorRole(course_key).has_user(user) or
        OrgInstructorRole(course_key.org).has_user(user)
    )

    return global_staff, staff_access, instructor_access


def _has_instructor_access_to_descriptor(user, descriptor, course_key):
    """Helper method that checks whether the user has staff access to
    the course of the location.

    descriptor: something that has a location attribute
    """
    return _has_instructor_access_to_location(user, descriptor.location, course_key)


def _has_staff_access_to_descriptor(user, descriptor, course_key):
    """Helper method that checks whether the user has staff access to
    the course of the location.

    descriptor: something that has a location attribute
    """
    return _has_staff_access_to_location(user, descriptor.location, course_key)


def _visible_to_nonstaff_users(descriptor):
    """
    Returns if the object is visible to nonstaff users.

    Arguments:
        descriptor: object to check
    """
    return VisibilityError() if descriptor.visible_to_staff_only else ACCESS_GRANTED


def _can_access_descriptor_with_milestones(user, descriptor, course_key):
    """
    Returns if the object is blocked by an unfulfilled milestone.

    Args:
        user: the user trying to access this content
        descriptor: the object being accessed
        course_key: key for the course for this descriptor
    """
    if milestones_helpers.get_course_content_milestones(course_key, unicode(descriptor.location), 'requires', user.id):
        debug("Deny: user has not completed all milestones for content")
        return ACCESS_DENIED
    else:
        return ACCESS_GRANTED


def _has_detached_class_tag(descriptor):
    """
    Returns if the given descriptor's type is marked as detached.

    Arguments:
        descriptor: object to check
    """
    return ACCESS_GRANTED if 'detached' in descriptor._class_tags else ACCESS_DENIED  # pylint: disable=protected-access


def _has_fulfilled_all_milestones(user, course_id):
    """
    Returns whether the given user has fulfilled all milestones for the
    given course.

    Arguments:
        course_id: ID of the course to check
        user_id: ID of the user to check
    """
    return MilestoneAccessError() if any_unfulfilled_milestones(course_id, user.id) else ACCESS_GRANTED


def _has_fulfilled_prerequisites(user, course_id):
    """
    Returns whether the given user has fulfilled all prerequisites for the
    given course.

    Arguments:
        user: user to check
        course_id: ID of the course to check
    """
    return MilestoneAccessError() if get_pre_requisite_courses_not_completed(user, course_id) else ACCESS_GRANTED


def _has_catalog_visibility(course, visibility_type):
    """
    Returns whether the given course has the given visibility type
    """
    return ACCESS_GRANTED if course.catalog_visibility == visibility_type else ACCESS_DENIED


def _is_descriptor_mobile_available(descriptor):
    """
    Returns if descriptor is available on mobile.
    """
    if IgnoreMobileAvailableFlagConfig.is_enabled() or descriptor.mobile_available:
        return ACCESS_GRANTED
    else:
        return MobileAvailabilityError()


def is_mobile_available_for_user(user, descriptor):
    """
    Returns whether the given course is mobile_available for the given user.
    Checks:
        mobile_available flag on the course
        Beta User and staff access overrides the mobile_available flag
    Arguments:
        descriptor (CourseDescriptor|CourseOverview): course or overview of course in question
    """
    return (
        auth.user_has_role(user, CourseBetaTesterRole(descriptor.id))
        or _has_staff_access_to_descriptor(user, descriptor, descriptor.id)
        or _is_descriptor_mobile_available(descriptor)
    )


def get_user_role(user, course_key):
    """
    Return corresponding string if user has staff, instructor or student
    course role in LMS.
    """
    role = get_masquerade_role(user, course_key)
    if role:
        return role
    elif has_access(user, 'instructor', course_key):
        return 'instructor'
    elif has_access(user, 'staff', course_key):
        return 'staff'
    else:
        return 'student'
