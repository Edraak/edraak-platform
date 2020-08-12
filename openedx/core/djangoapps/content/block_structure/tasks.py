"""
Asynchronous tasks related to the Course Blocks sub-application.
"""
import logging

from capa.responsetypes import LoncapaProblemError
from celery.task import task
from django.conf import settings
from lxml.etree import XMLSyntaxError

from edxval.api import ValInternalError
from opaque_keys.edx.keys import CourseKey

from xmodule.modulestore.exceptions import ItemNotFoundError
from openedx.core.djangoapps.content.block_structure import api
from openedx.core.djangoapps.content.block_structure.config import STORAGE_BACKING_FOR_CACHE, waffle

log = logging.getLogger('edx.celery.task')

# TODO: TNL-5799 is ongoing; narrow these lists down until the general exception is no longer needed
RETRY_TASKS = (ItemNotFoundError, TypeError, ValInternalError)
NO_RETRY_TASKS = (XMLSyntaxError, LoncapaProblemError, UnicodeEncodeError)


def block_structure_task(**kwargs):
    """
    Decorator for block structure tasks.
    """
    return task(
        default_retry_delay=settings.BLOCK_STRUCTURES_SETTINGS['TASK_DEFAULT_RETRY_DELAY'],
        max_retries=settings.BLOCK_STRUCTURES_SETTINGS['TASK_MAX_RETRIES'],
        bind=True,
        **kwargs
    )


@block_structure_task()
def update_course_in_cache_v2(self, **kwargs):
    """
    Updates the course blocks (mongo -> BlockStructure) for the specified course.
    Keyword Arguments:
        course_id (string) - The string serialized value of the course key.
        with_storage (boolean) - Whether or not storage backing should be
            enabled for the generated block structure(s).
    """
    _update_course_in_cache(self, **kwargs)


@block_structure_task()
def update_course_in_cache(self, course_id):
    """
    Updates the course blocks (mongo -> BlockStructure) for the specified course.
    """
    _update_course_in_cache(self, course_id=course_id)


def _update_course_in_cache(self, **kwargs):
    """
    Updates the course blocks (mongo -> BlockStructure) for the specified course.
    """
    if kwargs.get('with_storage'):
        waffle().override_for_request(STORAGE_BACKING_FOR_CACHE)
    _call_and_retry_if_needed(self, api.update_course_in_cache, **kwargs)


@block_structure_task()
def get_course_in_cache_v2(self, **kwargs):
    """
    Gets the course blocks for the specified course, updating the cache if needed.
    Keyword Arguments:
        course_id (string) - The string serialized value of the course key.
        with_storage (boolean) - Whether or not storage backing should be
            enabled for any generated block structure(s).
    """
    _get_course_in_cache(self, **kwargs)


@block_structure_task()
def get_course_in_cache(self, course_id):
    """
    Gets the course blocks for the specified course, updating the cache if needed.
    """
    _get_course_in_cache(self, course_id=course_id)


def _get_course_in_cache(self, **kwargs):
    """
    Gets the course blocks for the specified course, updating the cache if needed.
    """
    if kwargs.get('with_storage'):
        waffle().override_for_request(STORAGE_BACKING_FOR_CACHE)
    _call_and_retry_if_needed(self, api.get_course_in_cache, **kwargs)


def _call_and_retry_if_needed(self, api_method, **kwargs):
    """
    Calls the given api_method with the given course_id, retrying task_method upon failure.
    """
    try:
        course_key = CourseKey.from_string(kwargs['course_id'])
        api_method(course_key)
    except NO_RETRY_TASKS:
        # Known unrecoverable errors
        log.exception(
            "BlockStructure: %s encountered unrecoverable error in course %s, task_id %s",
            self.__name__,
            kwargs.get('course_id'),
            self.request.id,
        )
        raise
    except RETRY_TASKS as exc:
        log.exception("%s encountered expected error, retrying.", self.__name__)
        raise self.retry(kwargs=kwargs, exc=exc)
    except Exception as exc:
        log.exception(
            "BlockStructure: %s encountered unknown error in course %s, task_id %s. Retry #%d",
            self.__name__,
            kwargs.get('course_id'),
            self.request.id,
            self.request.retries,
        )
        raise self.retry(kwargs=kwargs, exc=exc)
