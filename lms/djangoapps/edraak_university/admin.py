"""
Django admin for university ID.
"""
from django.contrib import admin
from django.core.urlresolvers import reverse

from openedx.core.djangolib.markup import HTML, Text

from edraak_university.models import UniversityID


@admin.register(UniversityID)
class UniversityIDAdmin(admin.ModelAdmin):
    """Admin for University Student ID."""
    list_display = (
        'edraak_user',
        'course_key',
        'university_id',
        'section_number',
        'email',
        'date_created',
    )

    readonly_fields = ('user', 'course_key', 'date_created',)
    search_fields = ('user__email', 'user__username', 'course_key', 'university_id',)

    def edraak_user(self, university_id_obj):
        """
        Provides the username with a link for the User object in the admin.
        """
        user = university_id_obj.user
        return HTML(u'<a href="{url}">{name}</a>').format(
            name=Text(unicode(user)),
            url=Text(reverse('admin:auth_user_change', args=[user.pk])),
        )

    def email(self, profile):
        """
        Provides the email address for the University ID admin list.
        """
        return profile.user.email

    edraak_user.allow_tags = True
