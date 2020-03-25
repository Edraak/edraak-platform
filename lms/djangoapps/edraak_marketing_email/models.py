"""
Edraak-Marketing-Email-related models.
"""
from django.db import models
from django.contrib.auth import get_user_model


class UnsubscribedUser(models.Model):
    """
    Stores users that have opted out of receiving marketing emails.
    """
    class Meta(object):
        app_label = "edraak_marketing_email"

    user = models.OneToOneField(get_user_model(), db_index=True, on_delete=models.CASCADE)
