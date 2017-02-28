"""
Edraak ratelimit models to log the issues and allow removing limits.
"""

from django.db import models
from django.contrib.auth.models import User

from student.models import LoginFailures


class RateLimitedIP(models.Model):
    """
    A model to store IP-based ratelimits.
    """

    ip_address = models.GenericIPAddressField(primary_key=True)
    lockout_count = models.IntegerField(default=1, db_index=True)

    # This is informational, which aids search
    # In reality there could be many users for the same model, but I for now
    # need only the latest user.
    latest_user = models.ForeignKey(User, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    def __unicode__(self):
        """
        Human friendly name.
        """
        return self.ip_address

    class Meta:
        """
        Rename the model and make it a bit more user-friendly.
        """
        app_label = 'edraak_ratelimit'
        verbose_name = 'IP-based Lock'
        verbose_name_plural = 'IP-based Locks'


class StudentAccountLock(LoginFailures):
    """
    Make a proxy/fake LoginFailures model, to organize the admin panel a bit.

    The name of the model is also adjusted to be user friendly.
    """

    def __unicode__(self):
        """
        Human friendly name.
        """
        return u'{username} account lock'.format(username=self.user.username)

    class Meta:
        """
        Prevents generating migrations.
        """
        app_label = 'edraak_ratelimit'
        proxy = True
        managed = False
        auto_created = True
