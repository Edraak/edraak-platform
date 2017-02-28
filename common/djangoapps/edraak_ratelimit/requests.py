"""
Custom requests for the edraak_ratelimit.
"""


class FakeRequest(object):
    """
    A fake request class to preserve compatibility with `EdraakRateLimitModelBackend`.
    """
    def __init__(self, ip_address):
        """
        Provides the fake request object with a META['REMOTE_ADDR'] property.

        Args:
            ip_address: A string IP address e.g. 150.221.45.3
        """
        self.META = {  # pylint: disable=invalid-name
            'REMOTE_ADDR': ip_address,
        }
