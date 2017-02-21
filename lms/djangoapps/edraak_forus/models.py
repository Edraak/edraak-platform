from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone


class ForusProfile(models.Model):
    user = models.ForeignKey(User, unique=True, db_index=True)
    date_created = models.DateTimeField(_('date forus profile created'), default=timezone.now)

    @staticmethod
    def create_for_user(user):
        if user.is_staff or user.is_superuser:
            log.warn('Cannot create profile for superusers and staff. email=`%s`', user.email)
            raise Exception('Cannot create profile for superusers and staff')

        forus_profile = ForusProfile(user=user)
        forus_profile.save()

    @staticmethod
    def is_forus_user(user):
        if not user:
            return False

        try:
            ForusProfile.objects.get(user=user)
        except ForusProfile.DoesNotExist:
            return False
        else:
            return True
