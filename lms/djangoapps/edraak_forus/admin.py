"""
Django admin page for ForUs models
"""
from django.contrib import admin
from django.core.urlresolvers import reverse
from django.utils.html import escape

from student.models import UserProfile

from models import ForusProfile
from helpers import setfuncattr


class ForusProfileAdmin(admin.ModelAdmin):
    """Admin for ForUs profile."""
    list_display = ('edraak_user', 'edraak_profile', 'email', 'date_created')
    readonly_fields = ('user', 'date_created')
    search_fields = ('user__email', 'user__username')

    @setfuncattr('allow_tags', True)
    def edraak_user(self, profile):
        user = profile.user
        return u'<a href="{url}">{name}</a>'.format(
            name=escape(user.username),
            url=reverse('admin:auth_user_change', args=[user.pk]),
        )

    @setfuncattr('allow_tags', True)
    def edraak_profile(self, profile):
        try:
            edraak_profile = UserProfile.objects.get(user=profile.user)
        except UserProfile.DoesNotExist:
            return None

        return u'<a href="{url}">Edraak Profile</a>'.format(
            url=reverse('admin:student_userprofile_change', args=[edraak_profile.pk]),
        )

    def email(self, profile):
        return profile.user.email


admin.site.register(ForusProfile, ForusProfileAdmin)
