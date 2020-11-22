from urlparse import urljoin
import requests
from django.conf import settings
from edxmako.shortcuts import marketing_link
import logging
from rest_framework import status
from rest_framework.exceptions import APIException


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
    marketing_root_format = marketing_link('COURSE_DETAILS_API_FORMAT')
    url = marketing_root_format.format(course_id=course_key)

    try:
        response = requests.get(
            url=url,
            headers={'Accept-Language': language},
            timeout=settings.EDRAAK_MARKETING_API_TIMEOUT
        )
    except requests.exceptions.Timeout:
        raise APIException(
            {
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "developer_message": "Marketing courses API have timed out."
            },
            code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception:
        log.exception('Something went wrong with the marketing courses API')
        raise APIException(
            {
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "developer_message": "Marketing courses didn't respond correctly."
            },
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if response.status_code != 200:
        log.warning('Could not fetch the marketing details from the API. course_key=[%s], status_code=[%s], url=[%s].',
                    course_key, response.status_code, url)
        return {}
    return response.json()
