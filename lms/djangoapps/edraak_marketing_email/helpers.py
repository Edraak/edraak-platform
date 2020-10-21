from django.conf import settings
from edraak_marketing_email.models import UnsubscribedUser
from edraak_sendinblue.api_client import create_contact


def unsubscribe_from_marketing_emails(user):
    UnsubscribedUser.objects.get_or_create(user=user)
    change_sendinblue_user_state(user)


def subscribe_to_marketing_emails(user):
    UnsubscribedUser.objects.filter(user=user).delete()
    change_sendinblue_user_state(user)


def change_sendinblue_user_state(user):
    if hasattr(settings, "EDRAAK_SENDINBLUE_API_KEY") and settings.EDRAAK_SENDINBLUE_API_KEY:
        blacklisted = not UnsubscribedUser.is_user_subscribed(user=user)

        create_contact(
            email=user.email,
            name=user.profile.name,
            blacklisted=blacklisted
        )
