import requests
import logging

from urlparse import urljoin

from django.conf import settings
from django.core.cache import cache
from xmodule.modulestore.django import modulestore

from edxmako.shortcuts import marketing_link
from courseware.access import has_access
from courseware.grades import grade
from opaque_keys.edx import locator

from .constants import COURSE_MKTG_DETAILS_CACHE_KEY


log = logging.getLogger(__name__)


def cached_function(cache_key_format, timeout=30):
    """
    Decorator to cache heavy functions.

    Use it as the following:
    @cached_function("module.add_numbers.{0}.{1}", 30)
    def add_numbers(a, b):
        return a + b

    """
    def the_decorator(func):

        def cached_func(*args, **kwargs):
            cache_key = cache_key_format.format(*args, **kwargs)
            cached_result = cache.get(cache_key)

            if cached_result is not None:
                return cached_result
            else:
                result = func(*args, **kwargs)
                cache.set(cache_key, result, timeout)
                return result

        return cached_func

    return the_decorator


@cached_function(
    cache_key_format='edraak_misc.utils.is_student_pass.{0.id}.{2}',
    timeout=60*5  # Cache up to 5 minutes
)
def is_student_pass(user, request, course_id):
    course_key = locator.CourseLocator.from_string(course_id)
    course = modulestore().get_course(course_key)

    if not settings.FEATURES.get('ENABLE_ISSUE_CERTIFICATE'):
        return False

    # If user is course staff don't grade the user
    if has_access(user, 'staff', course):
        return True

    return bool(grade(user, request, course)['grade'])


def is_certificate_allowed(user, course):
    if not settings.FEATURES.get('ENABLE_ISSUE_CERTIFICATE'):
        return False

    if not course:
        return False

    return course.may_certify() or has_access(user, 'staff', course.id)


def sort_closed_courses_to_bottom(courses):
    """
    Sorts the courses by their `has_ended()`, open courses come first.
    """

    open_courses = [course for course in courses if not course.has_ended()]
    ended_courses = [course for course in courses if course.has_ended()]

    return open_courses + ended_courses


def filter_invitation_only_courses(courses):
    """
    Filter out the courses with invitation_only flag set to true.
    """

    return [course for course in courses if not course.invitation_only]


def edraak_courses_logic(courses):
    courses = filter_invitation_only_courses(courses)
    courses = sort_closed_courses_to_bottom(courses)
    return courses


def get_absolute_url_prefix(request):
    schema = 'https' if request.is_secure() else 'http'
    prefix = '{schema}://{host}'.format(schema=schema, host=settings.SITE_NAME)
    return prefix


def fetch_courses_marketing_details(request, course_ids):
    """
    Sends a request to the marketing site's API to retrieve all
    course details for course ids in passed in course_ids and saves
    the details in the cache.

    :param request:
    :param course_ids: a list of course_id strings
    :return: a list of course detail dictionaries. an empty list if
    no courses where retrieved from the marketing API
    """
    language = request.META.get(
        'ORIGINAL_HTTP_ACCEPT_LANGUAGE', settings.LANGUAGE_CODE)
    headers = {'Accept-Language': language}

    # Get the marketing url
    marketing_root = marketing_link('ROOT')
    # Marketing API path
    marketing_api = 'api/marketing/courses/'
    url = urljoin(marketing_root, marketing_api)

    response = requests.get(url, headers=headers, params={'ids': course_ids})
    if response.status_code != 200:
        return []

    courses = response.json().get('results')
    for course in courses:
        cache_key = COURSE_MKTG_DETAILS_CACHE_KEY.format(
            course_id=course['id']
        )
        try:
            cache_time_out = getattr(
                settings,
                'ENROLLMENT_COURSE_DETAILS_CACHE_TIMEOUT',
                60
            )
            cache.set(cache_key, course, cache_time_out)
        except Exception:
            log.exception(
                u"Error occurred while caching course enrollment details for course %s",
                course
            )
    return courses


def get_courses_marketing_details(request, course_ids):
    """
    gets the marketing site details from the cache if available or
    the marketing site api otherwise for all courses who's id is in
    the course_ids list.

    :param request:
    :param course_ids: a list of course_id strings
    :return:
    """
    details = {}
    fetch_courses = []
    for course_id in course_ids:
        cache_key = COURSE_MKTG_DETAILS_CACHE_KEY.format(
            course_id=course_id
        )
        cached_details = None
        try:
            cached_details = cache.get(cache_key)
        except Exception:
            log.exception(
                u"Error occurred while retrieving course enrollment details from the cache"
            )
        if cached_details:
            details[course_id] = cached_details
        else:
            fetch_courses.append(course_id)

    if not fetch_courses:
        return details

    for res in fetch_courses_marketing_details(request, fetch_courses):
        details[res['id']] = res

    return details
