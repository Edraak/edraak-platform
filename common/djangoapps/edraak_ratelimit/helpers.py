"""
Edraak ratelimit helpers.
"""


def update_authentication_backends(original_backends):
    """
    Patches the AUTHENTICATION_BACKENDS setting to replace `RateLimitModelBackend` with `EdraakRateLimitModelBackend`.

    Args:
        original_backends: the original backends tuple.

    Returns:
        The updated backends tuple.
    """
    edx_to_edraak_backends = {
        'ratelimitbackend.backends.RateLimitModelBackend':
            'edraak_ratelimit.backends.EdraakRateLimitModelBackend',

        'openedx.core.djangoapps.oauth_dispatch.dot_overrides.validators.EdxRateLimitedAllowAllUsersModelBackend':
            'edraak_ratelimit.backends.EdraakRateLimitAllowAllUsersModelBackend',
    }

    backends = original_backends[:]  # copy the list
    for edx_backend, edraak_backend in edx_to_edraak_backends.iteritems():
        backends = [
            edraak_backend if auth_backend == edx_backend else auth_backend
            for auth_backend in backends
        ]

    edraak_lms_backend, edraak_studio_backend = edx_to_edraak_backends.values()

    if (edraak_lms_backend not in backends) and (edraak_studio_backend not in backends):
        raise ValueError(
            'Edraak RateLimit backends was not added, this module probably needs an update '
            'to match the Open edX release..'
        )

    if (edraak_lms_backend in backends) and (edraak_studio_backend in backends):
        raise ValueError(
            'Both Edraak RateLimit backends have been added, this module probably needs an update '
            'to match the Open edX release..'
        )

    return backends


def humanize_delta(delta):
    """
    Provides a more human friendly delta description.

    This helper only cares about the most significant unit e.g.

        - '5 seconds and 3 minutes' will be shown as '3 minutes'
        - '1 years and 5 months' will be shown as '1 years'
        - and so on

    Args:
        delta: relativedelta object.

    Returns: str

        '1 years'
        '2 months'
        '20 minutes'
        '1 seconds'
        '0 seconds'
    """

    periods = ('days', 'seconds',)

    for period in periods:
        if hasattr(delta, period):
            count = getattr(delta, period)

            if count:
                return '{count} {period}'.format(
                    count=count,
                    period=period,
                )

    return '0 seconds'
