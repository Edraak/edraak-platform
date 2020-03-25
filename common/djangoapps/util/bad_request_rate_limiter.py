"""
A utility class which wraps the RateLimitMixin 3rd party class to do bad request counting
which can be used for rate limiting
"""
from ratelimitbackend.backends import RateLimitMixin
from django.conf import settings

if settings.FEATURES.get('EDRAAK_RATELIMIT_APP', False):
    from edraak_ratelimit.backends import EdraakRateLimitMixin
    RateLimitMixin = EdraakRateLimitMixin


class BadRequestRateLimiter(RateLimitMixin):
    """
    Use the 3rd party RateLimitMixin to help do rate limiting on the Password Reset flows
    """

    def is_rate_limit_exceeded(self, request):
        """
        Returns if the client has been rated limited
        """
        counts = self.get_counters(request)
        is_exceeded = sum(counts.values()) >= self.requests

        if is_exceeded:
            self.db_log_failed_attempt(request)

        return is_exceeded

    def tick_bad_request_counter(self, request):
        """
        Ticks any counters used to compute when rate limt has been reached
        """
        self.cache_incr(self.get_cache_key(request))
