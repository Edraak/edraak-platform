"""
Django admin page for ForUs models
"""
from django.contrib import admin
from django.core.urlresolvers import reverse

from openedx.core.djangolib.markup import HTML, Text

from edraak_forus.models import ForusProfile


class ForusProfileAdmin(admin.ModelAdmin):
    """
    Admin for ForUs profile.
    """
    list_display = ('edraak_user', 'email', 'date_created')
    readonly_fields = ('user', 'date_created')
    search_fields = ('user__email', 'user__username')

    def edraak_user(self, profile):
        """
        Return link to user
        """
        user = profile.user
        return HTML(u'<a href="{url}">{name}</a>').format(
            name=Text(user.username),
            url=Text(reverse('admin:auth_user_change', args=[user.pk])),
        )

    def email(self, profile):
        """
        Returns user email
        """
        return profile.user.email

    edraak_user.allow_tags = True

admin.site.register(ForusProfile, ForusProfileAdmin)
