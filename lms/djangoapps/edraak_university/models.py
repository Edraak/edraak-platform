"""
Models for the University ID apps.
"""

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _

from student.models import UserProfile

from openedx.core.djangoapps.xmodule_django.models import CourseKeyField


class UniversityID(models.Model):
    """
    Stores a the university ID and the section number for a students in university-run courses.
    """

    user = models.ForeignKey(User)
    course_key = CourseKeyField(max_length=255, db_index=True)
    university_id = models.CharField(verbose_name=_('Student University ID'), max_length=100)
    section_number = models.CharField(verbose_name=_('Section Number'), max_length=10)
    date_created = models.DateTimeField(default=timezone.now)

    # Will be used in `get_marked_university_ids()` method to mark
    # duplicate entries.
    is_conflicted = False

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
