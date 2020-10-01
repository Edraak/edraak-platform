"""
Edraak-Marketing-Email-related models.
"""
from django.db import models
from django.contrib.auth.models import User


class UnsubscribedUser(models.Model):
    """
    Stores users that have opted out of receiving marketing emails.
    """
    class Meta(object):
        app_label = "edraak_marketing_email"

    user = models.OneToOneField(User, db_index=True, on_delete=models.CASCADE)

    @classmethod
    def is_user_subscribed(cls, user):
        if cls.objects.filter(user=user).exists():
            return False

        return True
