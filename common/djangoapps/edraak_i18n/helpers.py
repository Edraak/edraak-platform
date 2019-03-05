"""
Helper functions to Edraak i18n module.
"""


def add_locale_middleware(middleware_classes):
    """
    Adds the Edraak's DefaultLocaleMiddleware to the MIDDLEWARE_CLASSES tuple correctly.

    This function is meant to be used within the settings files like lms/envs/aws.py and others.

    Args:
        middleware_classes: The MIDDLEWARE_CLASSES tuple from the settings.

    Returns:
        The new MIDDLEWARE_CLASSES with the edraak_i18n middleware.
    """

    edraak_middleware = 'edraak_i18n.middleware.DefaultLocaleMiddleware'

    other_locale_middlewares = (
        'openedx.core.djangoapps.lang_pref.middleware.LanguagePreferenceMiddleware',
        'openedx.core.djangoapps.dark_lang.middleware.DarkLangMiddleware',
        'django.middleware.locale.LocaleMiddleware',
    )

    indexes = [
        middleware_classes.index(class_name) for class_name in other_locale_middlewares
        if class_name in middleware_classes
    ]

    first_index = min(indexes)

    # Insert the DefaultLocaleMiddleware before any other locale-related middleware in order for it to work
    return middleware_classes[:first_index] + [edraak_middleware] + middleware_classes[first_index:]


def is_api_request(request):
    """
    Checks if the a request is targeting an API endpoint.

    Args:
        request: A django request.

    Returns: True if the request is an API request and False otherwise.
    """
    if request.path.startswith('/api/'):
        return True
    elif request.path.startswith('/user_api/'):
        return True
    elif request.path.startswith('/notifier_api/'):
        return True

    return False
