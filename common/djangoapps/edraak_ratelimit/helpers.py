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

    original_backend = 'ratelimitbackend.backends.RateLimitModelBackend'
    edraak_backend = 'edraak_ratelimit.backends.EdraakRateLimitModelBackend'

    index = original_backends.index(original_backend)

    return original_backends[:index] + (edraak_backend,) + original_backends[(index + 1):]


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
