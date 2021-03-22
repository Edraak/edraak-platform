""" Overrides for Docker-based devstack. """

from .devstack import *  # pylint: disable=wildcard-import, unused-wildcard-import

# Docker does not support the syslog socket at /dev/log. Rely on the console.
LOGGING['handlers']['local'] = LOGGING['handlers']['tracking'] = {
    'class': 'logging.NullHandler',
}

LOGGING['loggers']['tracking']['handlers'] = ['console']

# LMS_BASE = 'edx.devstack.lms:18000'
# CMS_BASE = 'edx.devstack.studio:18010'
# LMS_ROOT_URL = 'http://{}'.format(LMS_BASE)

FEATURES.update({
    'ENABLE_COURSEWARE_INDEX': False,
    'ENABLE_LIBRARY_INDEX': False,
    'ENABLE_DISCUSSION_SERVICE': True,
})

CREDENTIALS_SERVICE_USERNAME = 'credentials_worker'

OAUTH_OIDC_ISSUER = '{}/oauth2'.format(LMS_ROOT_URL)

JWT_AUTH.update({
    'JWT_SECRET_KEY': 'lms-secret',
    'JWT_ISSUER': OAUTH_OIDC_ISSUER,
    'JWT_AUDIENCE': 'lms-key',
})

EDRAAK_JWT_SETTINGS = {
    'EXPIRATION_SECONDS': 60 * 3,
    'REFRESH_EXPIRATION_SECONDS': 60 * 60 * 24 * 7,
    'SECRET_KEY': 'dev-dummy-key',
    'REFRESH_TOKEN_COOKIE_NAME': 'edraak_refresh_token',
}
