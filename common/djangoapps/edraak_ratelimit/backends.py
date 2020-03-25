"""
Edraak authentication backends apply rate limits.
"""

from ratelimitbackend.backends import RateLimitMixin
from ratelimitbackend.exceptions import RateLimitException
from django.db.models import F

from django.contrib.auth.models import User
from django.contrib.auth.backends import AllowAllUsersModelBackend, ModelBackend

from edraak_ratelimit.models import RateLimitedIP


class EdraakRateLimitMixin(RateLimitMixin):
    """
    Make the limit a little bit more permissive.
    """

    # Edraak (ratelimit): We're overriding the values to avoid patching ratelimit pip package itself.
    minutes = 5
    requests = 10000  # Make the limit a little bit more permissive

    def db_log_failed_attempt(self, request, username=None):
        """
        Store information about the failed attempt in the database.

        Args:
            request: WSGIRequest object.
        """
        user = None
        ip_address = request.META['REMOTE_ADDR']

        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                pass

        if not user:
            if hasattr(request, 'user') and request.user.is_authenticated():
                user = request.user

        try:
            limited_ip = RateLimitedIP.objects.get(ip_address=ip_address)
            limited_ip.lockout_count = F('lockout_count') + 1
        except RateLimitedIP.DoesNotExist:
            limited_ip = RateLimitedIP(ip_address=ip_address)

        # There could be multiple users, but storing the latest should be fine for our
        # limited intent to use it.
        limited_ip.latest_user = user
        limited_ip.save()

    def authenticate(self, **kwargs):
        """
        Authenticates a user (Django's default behaviour) and logs failed attempts in the database.

        Args:
            **kwargs: Whatever django's `ModelBackend` takes.
        """
        try:
            return super(EdraakRateLimitMixin, self).authenticate(**kwargs)
        except RateLimitException:
            request = kwargs.get('request')
            self.db_log_failed_attempt(request, kwargs[self.username_key])
            raise  # Keep it consistent with the RateLimitMixin logic


class EdraakRateLimitAllowAllUsersModelBackend(EdraakRateLimitMixin, AllowAllUsersModelBackend):
    """
    Log the locks in the database and allow fine-grained unlock.

    Allow inactive users for 3rd party apps with logging.
    """
    pass


class EdraakRateLimitModelBackend(EdraakRateLimitMixin, ModelBackend):
    """
    Log the locks in the database and allow fine-grained unlock.

    Allow inactive users for 3rd party apps with logging.
    """
    pass
