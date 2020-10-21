from django.contrib import admin
from edraak_marketing_email.models import UnsubscribedUser


@admin.register(UnsubscribedUser)
class EdraakMarketingEmailAdmin(admin.ModelAdmin):
    """ Admin interface for the UnsubscribedUser model. """
    list_display = ('user',)
    raw_id_fields = ('user',)
    search_fields = ('user__username',)

    class Meta(object):
        model = UnsubscribedUser


