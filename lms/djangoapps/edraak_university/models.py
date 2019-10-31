"""
Models for the University ID apps.
"""

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.utils.translation import ugettext, ugettext_lazy as _

from courseware.courses import get_course_by_id
from opaque_keys.edx.django.models import UsageKeyField
from openedx.core.djangoapps.course_groups.cohorts import (
    add_user_to_cohort,
    get_cohort,
    remove_user_from_cohort,
    get_course_cohorts,
)
from student.models import UserProfile


DEFAULT_COHORT_NAMES = [
    # edX chose to translate `DEFAULT_COHORT_NAME`, this is a disaster for Arabic platforms!
    "Default Group",
    ugettext("Default Group"),
]


class UniversityID(models.Model):
    """
    Stores a the university ID and the section number for a students in university-run courses.
    """

    user = models.ForeignKey(User)
    course_key = UsageKeyField(max_length=255, db_index=True)
    university_id = models.CharField(verbose_name=_('Student University ID'), max_length=100)

    # This is set=True once an instructor edits a student's record
    can_edit = models.BooleanField(default=True)

    date_created = models.DateTimeField(default=timezone.now)

    # Deprecated fields, kept for backward compatibility
    _section_number = models.CharField(db_column='section_number', max_length=10, blank=True, default='')
    _cohort = models.IntegerField(db_column='cohort_id', null=True)

    # Will be used in `get_marked_university_ids()` method to mark
    # duplicate entries.
    is_conflicted = False

    def get_cohort(self):
        return get_cohort(self.user, self.course_key)

    def set_cohort(self, cohort):
        current_cohort = self.get_cohort()

        if cohort.id != current_cohort.id:
            add_user_to_cohort(cohort, self.user.email)

    def remove_from_cohort(self):
        cohort = self.get_cohort()
        remove_user_from_cohort(cohort, username_or_email=self.user.email)

    def get_full_name(self):
        """
        Gets the student's full name, or none in case the user had no profile.
        """
        try:
            user_profile = UserProfile.objects.get(user=self.user)
            return user_profile.name
        except UserProfile.DoesNotExist:
            return None

    def get_email(self):
        """
        Gets the student's email.
        """
        return self.user.email

    @classmethod
    def get_cohorts_for_course(cls, course_key):
        course = get_course_by_id(course_key)

        cohorts_choices = [
            cohort for cohort in get_course_cohorts(course=course)
            if cohort.name not in DEFAULT_COHORT_NAMES
        ]

        return cohorts_choices

    def __unicode__(self):
        return u'{user} - {course_key} - {university_id}'.format(
            user=self.user,
            course_key=self.course_key,
            university_id=self.university_id,
        )

    @classmethod
    def get_marked_university_ids(cls, course_key):
        """
        Get all university IDs for a course and mark duplicate as `is_conflicted`.
        """
        queryset = cls.objects.filter(course_key=course_key)
        queryset = queryset.order_by('university_id')

        def cleanup_id(university_id_pk):
            """
            Trim an ID to make it easier to compare.
            """
            return university_id_pk.strip().lower()

        entries = list(queryset)
        for i, entry in enumerate(entries):
            if i > 0:  # Avoid IndexError
                prev_entry = entries[i - 1]
                if cleanup_id(entry.university_id) == cleanup_id(prev_entry.university_id):
                    entry.is_conflicted = True
                    prev_entry.is_conflicted = True

        return entries

    class Meta:
        unique_together = ('user', 'course_key',)
        app_label = 'edraak_university'


class UniversityIDSettings(models.Model):
    """
    This model stores university id settings for each course.
    """
    course_key = UsageKeyField(primary_key=True, max_length=255, db_index=True)
    registration_end_date = models.DateField(null=True, blank=True, verbose_name=_('Registration End Date'))
    terms_and_conditions = models.TextField(null=True, blank=True, verbose_name=_('Terms and Conditions'))

    def __unicode__(self):
        return unicode(self.course_key)

    class Meta:
        app_label = 'edraak_university'
