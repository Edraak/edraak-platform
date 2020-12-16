"""
Specific overrides to the base prod settings to make development easier.
"""

from os.path import abspath, dirname, join

from .aws import *  # pylint: disable=wildcard-import, unused-wildcard-import

# Don't use S3 in devstack, fall back to filesystem
del DEFAULT_FILE_STORAGE
COURSE_IMPORT_EXPORT_STORAGE = 'django.core.files.storage.FileSystemStorage'
USER_TASKS_ARTIFACT_STORAGE = COURSE_IMPORT_EXPORT_STORAGE

DEBUG = True
USE_I18N = True
DEFAULT_TEMPLATE_ENGINE['OPTIONS']['debug'] = DEBUG
# HTTPS = 'off'

################################ LOGGERS ######################################

import logging

# Disable noisy loggers
for pkg_name in ['track.contexts', 'track.middleware', 'dd.dogapi']:
    logging.getLogger(pkg_name).setLevel(logging.CRITICAL)


################################ EMAIL ########################################

EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
EMAIL_FILE_PATH = '/edx/src/ace_messages/'

################################# LMS INTEGRATION #############################

# LMS_BASE = "localhost:8000"
# LMS_ROOT_URL = "http://{}".format(LMS_BASE)
# FEATURES['PREVIEW_LMS_BASE'] = "preview." + LMS_BASE

########################### PIPELINE #################################

# Skip packaging and optimization in development
PIPELINE_ENABLED = False
STATICFILES_STORAGE = 'openedx.core.storage.DevelopmentStorage'

# Revert to the default set of finders as we don't want the production pipeline
STATICFILES_FINDERS = [
    'openedx.core.djangoapps.theming.finders.ThemeFilesFinder',
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

# Load development webpack donfiguration
WEBPACK_CONFIG_PATH = 'webpack.dev.config.js'

############################ PYFS XBLOCKS SERVICE #############################
# Set configuration for Django pyfilesystem

DJFS = {
    'type': 'osfs',
    'directory_root': 'cms/static/djpyfs',
    'url_root': '/static/djpyfs',
}

################################# CELERY ######################################

# By default don't use a worker, execute tasks as if they were local functions
CELERY_ALWAYS_EAGER = True

################################ DEBUG TOOLBAR ################################

INSTALLED_APPS += ['debug_toolbar', 'debug_toolbar_mongo']

MIDDLEWARE_CLASSES.append('debug_toolbar.middleware.DebugToolbarMiddleware')
INTERNAL_IPS = ('127.0.0.1',)

DEBUG_TOOLBAR_PANELS = (
    'debug_toolbar.panels.versions.VersionsPanel',
    'debug_toolbar.panels.timer.TimerPanel',
    'debug_toolbar.panels.settings.SettingsPanel',
    'debug_toolbar.panels.headers.HeadersPanel',
    'debug_toolbar.panels.request.RequestPanel',
    'debug_toolbar.panels.sql.SQLPanel',
    'debug_toolbar.panels.signals.SignalsPanel',
    'debug_toolbar.panels.logging.LoggingPanel',
    'debug_toolbar.panels.profiling.ProfilingPanel',
)

DEBUG_TOOLBAR_CONFIG = {
    # Profile panel is incompatible with wrapped views
    # See https://github.com/jazzband/django-debug-toolbar/issues/792
    'DISABLE_PANELS': (
        'debug_toolbar.panels.profiling.ProfilingPanel',
    ),
    'SHOW_TOOLBAR_CALLBACK': 'cms.envs.devstack.should_show_debug_toolbar',
}


def should_show_debug_toolbar(request):
    # We always want the toolbar on devstack unless running tests from another Docker container
    if request.get_host().startswith('edx.devstack.studio:'):
        return False
    return True


# To see stacktraces for MongoDB queries, set this to True.
# Stacktraces slow down page loads drastically (for pages with lots of queries).
DEBUG_TOOLBAR_MONGO_STACKTRACES = False


################################ MILESTONES ################################
FEATURES['MILESTONES_APP'] = True


################################ ENTRANCE EXAMS ################################
FEATURES['ENTRANCE_EXAMS'] = True

################################ COURSE LICENSES ################################
FEATURES['LICENSING'] = True
# Needed to enable licensing on video modules
XBLOCK_SETTINGS.update({'VideoDescriptor': {'licensing_enabled': True}})

################################ SEARCH INDEX ################################
FEATURES['ENABLE_COURSEWARE_INDEX'] = True
FEATURES['ENABLE_LIBRARY_INDEX'] = True
SEARCH_ENGINE = "search.elastic.ElasticSearchEngine"

########################## Certificates Web/HTML View #######################
FEATURES['CERTIFICATES_HTML_VIEW'] = True

########################## AUTHOR PERMISSION #######################
FEATURES['ENABLE_CREATOR_GROUP'] = False

###################### Edraak Feature ######################
FEATURES['EDRAAK_UNIVERSITY_APP'] = True

################################# DJANGO-REQUIRE ###############################

# Whether to run django-require in debug mode.
REQUIRE_DEBUG = DEBUG

########################### OAUTH2 #################################
OAUTH_OIDC_ISSUER = 'http://127.0.0.1:8000/oauth2'

JWT_AUTH.update({
    'JWT_SECRET_KEY': 'lms-secret',
    'JWT_ISSUER': 'http://127.0.0.1:8000/oauth2',
    'JWT_AUDIENCE': 'lms-key',
})

#####################################################################
from openedx.core.djangoapps.plugins import plugin_settings, constants as plugin_constants
plugin_settings.add_plugins(__name__, plugin_constants.ProjectType.CMS, plugin_constants.SettingsType.DEVSTACK)

###############################################################################
# See if the developer has any local overrides.
if os.path.isfile(join(dirname(abspath(__file__)), 'private.py')):
    from .private import *  # pylint: disable=import-error,wildcard-import

#####################################################################
# Lastly, run any migrations, if needed.
MODULESTORE = convert_module_store_setting_if_needed(MODULESTORE)

# Dummy secret key for dev
SECRET_KEY = '85920908f28904ed733fe576320db18cabd7b6cd'
