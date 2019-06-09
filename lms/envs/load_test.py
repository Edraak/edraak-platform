"""
Settings for load testing.
"""

# We intentionally define lots of variables that aren't used, and
# want to import all variables from base settings files
# pylint: disable=wildcard-import, unused-wildcard-import

from .aws import *

# Disable CSRF for load testing
EXCLUDE_CSRF = lambda elem: elem not in [
    'django.template.context_processors.csrf',
    # Replaced by Edraak to allow cross origin CSRF
    # 'django.middleware.csrf.CsrfViewMiddleware',
    'openedx.core.djangoapps.cors_csrf.middleware.CrossDomainCsrfViewMiddleware',
]
DEFAULT_TEMPLATE_ENGINE['OPTIONS']['context_processors'] = filter(
    EXCLUDE_CSRF, DEFAULT_TEMPLATE_ENGINE['OPTIONS']['context_processors']
)
MIDDLEWARE_CLASSES = filter(EXCLUDE_CSRF, MIDDLEWARE_CLASSES)
