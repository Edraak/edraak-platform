""" Edraak custom helper methods for CourseModes. """
from django.conf import settings
from django.core.urlresolvers import reverse
from django.utils.translation import get_language

from edxmako.shortcuts import marketing_link


def is_marketing_course_success_page_enabled():
    """
    Checks if the feature is enabled, while making some sanity checks along the way!
    """
    if not settings.FEATURES.get('EDRAAK_USE_MARKETING_COURSE_SUCCESS_PAGE'):
        return False

    base_message = 'You have enabled the `EDRAAK_USE_MARKETING_COURSE_SUCCESS_PAGE` feature'

    if not settings.FEATURES.get('ENABLE_MKTG_SITE'):
        raise Exception('{base} {other}'.format(
            base=base_message,
            other='without enabling the marketing site. Please enable the latter with the '
                  '`ENABLE_MKTG_SITE` feature flag.',
        ))

    mktg_urls_message = '{base} {other}'.format(
        base=base_message,
        other='but did not configure either COURSE_SUCCESS_PAGE_FORMAT or ROOT in the MKTG_URLS.',
    )

    try:
        if not settings.MKTG_URLS['ROOT'] or not settings.MKTG_URLS['COURSE_SUCCESS_PAGE_FORMAT']:
            raise Exception(mktg_urls_message)
    except KeyError:
        raise Exception(mktg_urls_message)

    if '{course_id}' not in settings.MKTG_URLS['COURSE_SUCCESS_PAGE_FORMAT']:
        raise Exception('{base} {other}'.format(
            base=base_message,
            other='but COURSE_SUCCESS_PAGE_FORMAT does not contain the formatting argument `course_id`.',
        ))

    return True


def get_course_success_page_url(course_id):
    if is_marketing_course_success_page_enabled():
        marketing_root_format = marketing_link('COURSE_SUCCESS_PAGE_FORMAT')
        return marketing_root_format.format(course_id=course_id)
    else:
        return reverse('dashboard')


def get_progs_url(page):
    lang = ''

    if get_language() != 'ar':
        lang = 'en/'

    root = settings.PROGS_URLS['ROOT']

    if root[-1:] != '/':
        root += '/'

    if page[:1] == '/':
        page = page[-(len(page) - 1):]

    url = "{root}{lang}{page}".format(
        root=root,
        lang=lang,
        page=page)

    return url
