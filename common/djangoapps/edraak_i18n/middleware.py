"""
Edraak i18n Middleware
"""

from django.conf import settings
from django.utils.translation import LANGUAGE_SESSION_KEY
from edraak_i18n.helpers import is_api_request


class DefaultLocaleMiddleware(object):
    """
    Changes the language to `settings.LANGUAGE_CODE` for all non-API requests.

    This will force the i18n machinery to always choose settings.LANGUAGE_CODE
    as the default initial language, unless another one is set via sessions or cookies.

    Should be installed *before* any middleware that checks request.META['HTTP_ACCEPT_LANGUAGE'],
    specifically django.middleware.locale.LocaleMiddleware

    Although the middleware is installed by default, it sill checks for the feature flag below in order to work.

      - `EDRAAK_I18N_LOCALE_MIDDLEWARE`
    """

    def process_request(self, request):
        """
        Changes request's `HTTP_ACCEPT_LANGUAGE` to `settings.LANGUAGE_CODE`.
        """

        # Edraak (hack): The DefaultLocaleMiddleware is disabled by default during tests, which is not very accurate.
        if not settings.FEATURES.get('EDRAAK_I18N_LOCALE_MIDDLEWARE'):
            return

        if 'HTTP_X_API_ACCEPT_LANGUAGE' in request.META:
            # Override the API accept language
            request.META[HTTP_ACCEPT_LANGUAGE] = request.META['HTTP_X_API_ACCEPT_LANGUAGE']
            return

        if is_api_request(request):
            # This middleware is only needed for browser page, it's effect is breaking the behaviour on the mobile
            # apps.
            return

        if 'HTTP_ACCEPT_LANGUAGE' in request.META:
            # Preserve the original value just in case,
            # the underscore prefix means that you probably shouldn't be using it anyway
            request.META['_HTTP_ACCEPT_LANGUAGE'] = request.META['HTTP_ACCEPT_LANGUAGE']

        # Make the accept language as same as the site original language regardless of the original value
        # Django will use this value in the LocaleMiddleware to display the correct translation
        request.META['HTTP_ACCEPT_LANGUAGE'] = settings.LANGUAGE_CODE
