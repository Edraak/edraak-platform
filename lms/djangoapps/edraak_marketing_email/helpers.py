from edraak_marketing_email.models import UnsubscribedUser


def unsubscribe_from_marketing_emails(user):
    UnsubscribedUser.objects.get_or_create(user=user)


def subscribe_to_marketing_emails(user):
    UnsubscribedUser.objects.filter(user=user).delete()
