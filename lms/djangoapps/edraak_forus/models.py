"""
Edraak ForUs models
"""
import logging
from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone
from edraak_forus.exceptions import ForusError

log = logging.getLogger(__name__)


class ForusProfile(models.Model):
    """
    ForUs users model
    """
    user = models.OneToOneField(User)
    date_created = models.DateTimeField(_('date forus profile created'), default=timezone.now)

    def __unicode__(self):
        return unicode(repr(self))

    @classmethod
    def create_for_user(cls, user):
        """
        Create ForUs users
        """
        if user.is_staff or user.is_superuser:
            log.warn('Cannot create profile for superusers and staff. email=`%s`', user.email)
            raise ForusError('Cannot create profile for superusers and staff')

        forus_profile = cls(user=user)
        forus_profile.save()

    @classmethod
    def is_forus_user(cls, user):
        """
        Checks if user is a ForUs user
        """
        if not user:
            return False

        try:
            cls.objects.get(user=user)
        except cls.DoesNotExist:
            return False
        else:
            return True
