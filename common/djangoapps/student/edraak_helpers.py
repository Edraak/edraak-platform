""" Edraak Specific Helpers """

import re

from django.conf import settings


def is_origin_url_allowed(origin):
    """
    An Edraak change to determine if we can redirect the user to the
    requested origin or not. Allowed origins are identified in the
    configs files.
    :param origin The requested origin
    :return: True if we can redirect, False otherwise
    """
    allowed = False

    if settings.FEATURES.get('EDRAAK_ENABLE_AUTH_EXTERNAL_REDIRECT'):
        # Check if origin is a safe origin
        all_allowed = settings.FEATURES.get('EDRAAK_AUTH_REDIRECT_ALLOW_ANY') or False
        origin_allowed = origin in (settings.FEATURES.get('EDRAAK_AUTH_REDIRECT_ORIGINS_WHITELIST') or [])

        # Check if the origin matches any allowed pattern
        patterns = settings.FEATURES.get('EDRAAK_AUTH_REDIRECT_REGX_ORIGINS') or []
        evaluated_origins = filter(lambda x: re.match(x, origin), patterns)
        pattern_allowed = any(evaluated_origins)

        allowed = all_allowed or origin_allowed or pattern_allowed

    return allowed


def edraak_update_origin(request, context):
    """
    Check if the origin is a safe (trusted) url. If so; pass it
    to the front end to allow navigating back to the originating
    site after authentication.
    """
    origin_url = request.GET.get('origin')

    if origin_url and is_origin_url_allowed(origin_url):
        context['data']['origin'] = origin_url
