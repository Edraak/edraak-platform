from urlparse import urljoin
import requests
from django.conf import settings
from edxmako.shortcuts import marketing_link
import logging
from django.core.cache import cache
import json
log = logging.getLogger(__name__)


def is_marketing_api_enabled():
    """
    Checks if the feature is enabled, while making some sanity checks along the way!
    """
    if not settings.FEATURES.get('EDRAAK_USE_MARKETING_COURSE_DETAILS_API'):
        return False

    base_message = 'You have enabled the `EDRAAK_USE_MARKETING_COURSE_DETAILS_API` feature'

    if not settings.FEATURES.get('ENABLE_MKTG_SITE'):
        raise Exception('{base} {other}'.format(
            base=base_message,
            other='without enabling the marketing site. Please enable the latter with the '
                  '`ENABLE_MKTG_SITE` feature flag.',
        ))

    mktg_urls_message = '{base} {other}'.format(
        base=base_message,
        other='but did not configure either COURSE_DETAILS_API_FORMAT or ROOT in the MKTG_URLS.',
    )

    try:
        if not settings.MKTG_URLS['ROOT'] or not settings.MKTG_URLS['COURSE_DETAILS_API_FORMAT']:
            raise Exception(mktg_urls_message)
    except KeyError:
        raise Exception(mktg_urls_message)

    if '{course_id}' not in settings.MKTG_URLS['COURSE_DETAILS_API_FORMAT']:
        raise Exception('{base} {other}'.format(
            base=base_message,
            other='but COURSE_DETAILS_API_FORMAT does not contain the formatting argument `course_id`.',
        ))

    return True


def get_marketing_data(course_key, language):
    """
    This method gets the current marketing details for a specific
    course.
    :returns a course details from the marketing API or None if
    no marketing details found.
    """
    from enrollment import time_block
    CACHE_KEY = "MKTG_API_" + str(course_key) + str(language)
    with time_block(CACHE_KEY, 5):
        if cache.get(CACHE_KEY):
            return cache.get(CACHE_KEY)
        marketing_root_format = marketing_link('COURSE_DETAILS_API_FORMAT')
        url = marketing_root_format.format(course_id=course_key)
    
        response = requests.get(url=url, headers={
            'Accept-Language': language,
        })
    
        if response.status_code != 200:
            log.warning('Could not fetch the marketing details from the API. course_key=[%s], status_code=[%s], url=[%s].',
                        course_key, response.status_code, url)
            return {}
        cache.set(CACHE_KEY, response.json(), 30 * 60)
        response_json = response.json() 
    return response_json
