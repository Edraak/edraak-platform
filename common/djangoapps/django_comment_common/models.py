import json
import logging

from config_models.models import ConfigurationModel
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import ugettext_noop
from jsonfield.fields import JSONField
from opaque_keys.edx.django.models import CourseKeyField
from six import text_type

from openedx.core.djangoapps.xmodule_django.models import NoneToEmptyManager
from student.models import CourseEnrollment
from student.roles import GlobalStaff
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError

FORUM_ROLE_ADMINISTRATOR = ugettext_noop('Administrator')
FORUM_ROLE_MODERATOR = ugettext_noop('Moderator')
FORUM_ROLE_GROUP_MODERATOR = ugettext_noop('Group Moderator')
FORUM_ROLE_COMMUNITY_TA = ugettext_noop('Community TA')
FORUM_ROLE_STUDENT = ugettext_noop('Student')


@receiver(post_save, sender=CourseEnrollment)
def assign_default_role_on_enrollment(sender, instance, **kwargs):
    """
    Assign forum default role 'Student'
    """
    # The code below would remove all forum Roles from a user when they unenroll
    # from a course. Concerns were raised that it should apply only to students,
    # or that even the history of student roles is important for research
    # purposes. Since this was new functionality being added in this release,
    # I'm just going to comment it out for now and let the forums team deal with
    # implementing the right behavior.
    #
    # # We've unenrolled the student, so remove all roles for this course
    # if not instance.is_active:
    #     course_roles = list(Role.objects.filter(course_id=instance.course_id))
    #     instance.user.roles.remove(*course_roles)
    #     return

    # We've enrolled the student, so make sure they have the Student role
    assign_default_role(instance.course_id, instance.user)


def assign_default_role(course_id, user):
    """
    Assign forum default role 'Student' to user
    """
    assign_role(course_id, user, FORUM_ROLE_STUDENT)


def assign_role(course_id, user, rolename):
    """
    Assign forum role `rolename` to user
    """
    role, created = Role.objects.get_or_create(course_id=course_id, name=rolename)
    if created:
        logging.info("EDUCATOR-1635: Created role {} for course {}".format(role, course_id))
    user.roles.add(role)


class Role(models.Model):

    objects = NoneToEmptyManager()

    name = models.CharField(max_length=30, null=False, blank=False)
    users = models.ManyToManyField(User, related_name="roles")
    course_id = CourseKeyField(max_length=255, blank=True, db_index=True)

    class Meta(object):
        # use existing table that was originally created from django_comment_client app
        db_table = 'django_comment_client_role'

    def __unicode__(self):
        # pylint: disable=no-member
        return self.name + " for " + (text_type(self.course_id) if self.course_id else "all courses")

    # TODO the name of this method is a little bit confusing,
    # since it's one-off and doesn't handle inheritance later
    def inherit_permissions(self, role):
        """
        Make this role inherit permissions from the given role.
        Permissions are only added, not removed. Does not handle inheritance.
        """
        if role.course_id and role.course_id != self.course_id:
            logging.warning(
                "%s cannot inherit permissions from %s due to course_id inconsistency",
                self,
                role,
            )
        for per in role.permissions.all():
            self.add_permission(per)

    def add_permission(self, permission):
        self.permissions.add(Permission.objects.get_or_create(name=permission)[0])

    def has_permission(self, permission):
        """Returns True if this role has the given permission, False otherwise."""
        course = modulestore().get_course(self.course_id)
        if course is None:
            raise ItemNotFoundError(self.course_id)
        if permission_blacked_out(course, {self.name}, permission):
            return False

        return self.permissions.filter(name=permission).exists()

    @staticmethod
    def user_has_role_for_course(user, course_id, role_names):
        """
        Returns True if the user has one of the given roles for the given course
        """
        return Role.objects.filter(course_id=course_id, name__in=role_names, users=user).exists()


class Permission(models.Model):
    name = models.CharField(max_length=30, null=False, blank=False, primary_key=True)
    roles = models.ManyToManyField(Role, related_name="permissions")

    class Meta(object):
        # use existing table that was originally created from django_comment_client app
        db_table = 'django_comment_client_permission'

    def __unicode__(self):
        return self.name


def permission_blacked_out(course, role_names, permission_name):
    """Returns true if a user in course with the given roles would have permission_name blacked out.

    This will return true if it is a permission that the user might have normally had for the course, but does not have
    right this moment because we are in a discussion blackout period (as defined by the settings on the course module).
    Namely, they can still view, but they can't edit, update, or create anything. This only applies to students, as
    moderators of any kind still have posting privileges during discussion blackouts.
    """
    return (
        not course.forum_posts_allowed and
        role_names == {FORUM_ROLE_STUDENT} and
        any([permission_name.startswith(prefix) for prefix in ['edit', 'update', 'create']])
    )


def all_permissions_for_user_in_course(user, course_id):  # pylint: disable=invalid-name
    """Returns all the permissions the user has in the given course."""
    if not user.is_authenticated:
        return {}

    course = modulestore().get_course(course_id)
    if course is None:
        raise ItemNotFoundError(course_id)

    roles = Role.objects.filter(users=user, course_id=course_id)
    role_names = {role.name for role in roles}

    permission_names = set()
    for role in roles:
        # Intentional n+1 query pattern to get permissions for each role because
        # Aurora's query optimizer can't handle the join proplerly on 30M+ row
        # tables (EDUCATOR-3374). Fortunately, there are very few forum roles.
        for permission in role.permissions.all():
            if not permission_blacked_out(course, role_names, permission.name):
                permission_names.add(permission.name)

    # Prevent a circular import
    from django_comment_common.utils import GLOBAL_STAFF_ROLE_PERMISSIONS

    if GlobalStaff().has_user(user):
        for permission in GLOBAL_STAFF_ROLE_PERMISSIONS:
            permission_names.add(permission)

    return permission_names


class ForumsConfig(ConfigurationModel):
    """Config for the connection to the cs_comments_service forums backend."""

    connection_timeout = models.FloatField(
        default=5.0,
        help_text="Seconds to wait when trying to connect to the comment service.",
    )

    @property
    def api_key(self):
        """The API key used to authenticate to the comments service."""
        return getattr(settings, "COMMENTS_SERVICE_KEY", None)

    def __unicode__(self):
        """Simple representation so the admin screen looks less ugly."""
        return u"ForumsConfig: timeout={}".format(self.connection_timeout)


class CourseDiscussionSettings(models.Model):
    course_id = CourseKeyField(
        unique=True,
        max_length=255,
        db_index=True,
        help_text="Which course are these settings associated with?",
    )
    discussions_id_map = JSONField(
        null=True,
        blank=True,
        help_text="Key/value store mapping discussion IDs to discussion XBlock usage keys.",
    )
    always_divide_inline_discussions = models.BooleanField(default=False)
    _divided_discussions = models.TextField(db_column='divided_discussions', null=True, blank=True)  # JSON list

    COHORT = 'cohort'
    ENROLLMENT_TRACK = 'enrollment_track'
    NONE = 'none'
    ASSIGNMENT_TYPE_CHOICES = ((NONE, 'None'), (COHORT, 'Cohort'), (ENROLLMENT_TRACK, 'Enrollment Track'))
    division_scheme = models.CharField(max_length=20, choices=ASSIGNMENT_TYPE_CHOICES, default=NONE)

    @property
    def divided_discussions(self):
        """Jsonify the divided_discussions"""
        return json.loads(self._divided_discussions)

    @divided_discussions.setter
    def divided_discussions(self, value):
        """Un-Jsonify the divided_discussions"""
        self._divided_discussions = json.dumps(value)


class DiscussionsIdMapping(models.Model):
    """This model is a performance optimization, updated on course publish."""
    course_id = CourseKeyField(db_index=True, primary_key=True, max_length=255)
    mapping = JSONField(
        help_text="Key/value store mapping discussion IDs to discussion XBlock usage keys.",
    )

    @classmethod
    def update_mapping(cls, course_key, discussions_id_map):
        """Update the mapping of discussions IDs to XBlock usage key strings."""
        mapping_entry, created = cls.objects.get_or_create(
            course_id=course_key,
            defaults={
                'mapping': discussions_id_map,
            },
        )
        if not created:
            mapping_entry.mapping = discussions_id_map
            mapping_entry.save()
