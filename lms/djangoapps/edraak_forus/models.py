"""
Edraak ForUs models
"""
import logging
from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone

log = logging.getLogger(__name__)


class ForusProfile(models.Model):
    """
    ForUs users model
    """
    user = models.ForeignKey(User, unique=True, db_index=True)
    date_created = models.DateTimeField(_('date forus profile created'), default=timezone.now)

    def __unicode__(self):
        return unicode(repr(self))

    @staticmethod
    # pylint: disable=missing-docstring
    def create_for_user(user):
        if user.is_staff or user.is_superuser:
            log.warn('Cannot create profile for superusers and staff. email=`%s`', user.email)
            raise Exception('Cannot create profile for superusers and staff')

        forus_profile = ForusProfile(user=user)
        forus_profile.save()

    @staticmethod
    # pylint: disable=missing-docstring
    def is_forus_user(user):
        if not user:
            return False

        try:
            ForusProfile.objects.get(user=user)
        except ForusProfile.DoesNotExist:
            return False
        else:
            return True
