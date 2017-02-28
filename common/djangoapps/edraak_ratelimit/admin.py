"""
Admin panel to report the ratelimits and allow cancelling them.
"""

from dateutil.relativedelta import relativedelta
import datetime

from django.core.cache import cache
from django.contrib.admin import DateFieldListFilter
from django.contrib import admin

from edraak_ratelimit.models import RateLimitedIP, StudentAccountLock
from edraak_ratelimit.backends import EdraakRateLimitModelBackend
from edraak_ratelimit.requests import FakeRequest
from edraak_ratelimit.helpers import humanize_delta


class RateLimitedIPAdmin(admin.ModelAdmin):
    """
    Admin for RateLimitedIP model.
    """

    actions = ['reset_attempts']

    readonly_fields = (
        'ip_address',
        'latest_user',
        'created_at',
        'updated_at',
        'lockout_count',
    )

    list_display = (
        '__unicode__',
        'latest_user',
        'lockout_count',
        'lockout_duration',
        'unlock_time',
        'created_at',
        'updated_at',
    )

    search_fields = (
        'ip_address',
        'latest_user__username',
        'latest_user__email',
    )

    list_filter = (
        ('updated_at', DateFieldListFilter),
    )

    ordering = ('-updated_at',)

    def lockout_duration(self, obj):
        """
        Return a human friendly duration.
        """
        delta = relativedelta(obj.updated_at, obj.created_at)
        return humanize_delta(delta)

    def unlock_time(self, obj):
        """
        Calculates the nearest time to unlock the authenticate attempts.
        """
        unlock_duration = datetime.timedelta(minutes=EdraakRateLimitModelBackend.minutes)
        return obj.updated_at + unlock_duration

    def get_actions(self, request):
        """
        Remove Django's `delete_selected` in order to use `reset_attempts` instead.
        """
        actions = super(RateLimitedIPAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def reset_attempts(self, request, queryset):
        """
        Reset attemps action in the admin dropdown.
        """
        for obj in queryset:
            self.delete_model(request, obj)

    def delete_model(self, request, obj):
        """
        Delete a model and reset it's attempts in the cache.
        """
        backend = EdraakRateLimitModelBackend()
        cache_keys = backend.keys_to_check(request=FakeRequest(obj.ip_address))
        cache.delete_many(cache_keys)
        obj.delete()


class StudentAccountLockAdmin(admin.ModelAdmin):
    """
    An admin for the `StudentAccountLock` admin.
    """

    search_fields = (
        'user__email', 'user__username', 'user__pk',
    )

    readonly_fields = (
        'user', 'failure_count', 'lockout_until',
    )

    list_display = (
        'email', 'username', 'failure_count', 'lockout_until',
    )

    def email(self, login_failures):
        """
        Provides the user email for the admin list.
        """
        return login_failures.user.email

    def username(self, login_failures):
        """
        Provides the username for the admin list.
        """
        return login_failures.user.username


admin.site.register(StudentAccountLock, StudentAccountLockAdmin)

admin.site.register(RateLimitedIP, RateLimitedIPAdmin)
