from functools import wraps

from ..backends.forus import ForUsOAuth2


def forus_authentication_only(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if isinstance(kwargs.get('backend'), ForUsOAuth2):
            return func(*args, **kwargs)
    return wrapper
