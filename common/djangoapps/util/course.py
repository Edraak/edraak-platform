"""
Utility methods related to course
"""
import logging
import urllib

from django.conf import settings

from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

log = logging.getLogger(__name__)

COURSE_SHARING_UTM_PARAMETERS = {
    'facebook': {
        'utm_medium': 'social',
        'utm_campaign': 'social-sharing-db',
        'utm_source': 'facebook',
    },
    'twitter': {
        'utm_medium': 'social',
        'utm_campaign': 'social-sharing-db',
        'utm_source': 'twitter',
    },
}


def get_encoded_course_sharing_utm_params():
    """
    Returns encoded Course Sharing UTM Parameters.
    """
    return {
        utm_source: urllib.urlencode(utm_params)
        for utm_source, utm_params in COURSE_SHARING_UTM_PARAMETERS.iteritems()
    }


def get_link_for_about_page(course):
    """
    Arguments:
        course: This can be either a course overview object or a course descriptor.

    Returns the course sharing url, this can be one of course's social sharing url, marketing url, or
    lms course about url.
    """
    is_social_sharing_enabled = configuration_helpers.get_value(
        'SOCIAL_SHARING_SETTINGS',
        getattr(settings, 'SOCIAL_SHARING_SETTINGS', {})
    ).get('CUSTOM_COURSE_URLS')
    if is_social_sharing_enabled and course.social_sharing_url:
        course_about_url = course.social_sharing_url
    elif settings.FEATURES.get('ENABLE_MKTG_SITE') and getattr(course, 'marketing_url', None):
        course_about_url = course.marketing_url
    else:
        course_about_url = u'{about_base_url}/courses/{course_key}/about'.format(
            about_base_url=configuration_helpers.get_value('LMS_ROOT_URL', settings.LMS_ROOT_URL),
            course_key=unicode(course.id),
        )

    return course_about_url


def has_certificates_enabled(course):
    """
    Arguments:
        course: This can be either a course overview object or a course descriptor.
    Returns a boolean if the course has enabled certificates
    """
    if not settings.FEATURES.get('CERTIFICATES_HTML_VIEW', False):
        return False
    return course.cert_html_view_enabled
