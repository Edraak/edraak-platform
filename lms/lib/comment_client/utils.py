"""" Common utilities for comment client wrapper """
import logging
from contextlib import contextmanager
from time import time
from uuid import uuid4

import requests
from django.utils.translation import get_language
from django.core.cache import cache
from django.contrib.auth.models import User

import dogstats_wrapper as dog_stats_api

from openedx.core.djangoapps.request_cache.middleware import request_cached
from .settings import SERVICE_HOST as COMMENTS_SERVICE

log = logging.getLogger(__name__)


def strip_none(dic):
    return dict([(k, v) for k, v in dic.iteritems() if v is not None])


def strip_blank(dic):
    def _is_blank(v):
        return isinstance(v, str) and len(v.strip()) == 0
    return dict([(k, v) for k, v in dic.iteritems() if not _is_blank(v)])


def extract(dic, keys):
    if isinstance(keys, str):
        return strip_none({keys: dic.get(keys)})
    else:
        return strip_none({k: dic.get(k) for k in keys})


@contextmanager
def request_timer(request_id, method, url, tags=None):
    start = time()
    with dog_stats_api.timer('comment_client.request.time', tags=tags):
        yield
    end = time()
    duration = end - start

    log.info(
        u"comment_client_request_log: request_id={request_id}, method={method}, "
        u"url={url}, duration={duration}".format(
            request_id=request_id,
            method=method,
            url=url,
            duration=duration
        )
    )


def perform_request(method, url, data_or_params=None, raw=False,
                    metric_action=None, metric_tags=None, paged_results=False):
    # To avoid dependency conflict
    from django_comment_common.models import ForumsConfig
    config = ForumsConfig.current()

    if not config.enabled:
        raise CommentClientMaintenanceError('service disabled')

    if metric_tags is None:
        metric_tags = []

    metric_tags.append(u'method:{}'.format(method))
    if metric_action:
        metric_tags.append(u'action:{}'.format(metric_action))

    if data_or_params is None:
        data_or_params = {}
    headers = {
        'X-Edx-Api-Key': config.api_key,
        'Accept-Language': get_language(),
    }
    request_id = uuid4()
    request_id_dict = {'request_id': request_id}

    if method in ['post', 'put', 'patch']:
        data = data_or_params
        params = request_id_dict
    else:
        data = None
        params = data_or_params.copy()
        params.update(request_id_dict)
    with request_timer(request_id, method, url, metric_tags):
        response = requests.request(
            method,
            url,
            data=data,
            params=params,
            headers=headers,
            timeout=config.connection_timeout
        )

    metric_tags.append(u'status_code:{}'.format(response.status_code))
    if response.status_code > 200:
        metric_tags.append(u'result:failure')
    else:
        metric_tags.append(u'result:success')

    dog_stats_api.increment('comment_client.request.count', tags=metric_tags)

    if 200 < response.status_code < 500:
        raise CommentClientRequestError(response.text, response.status_code)
    # Heroku returns a 503 when an application is in maintenance mode
    elif response.status_code == 503:
        raise CommentClientMaintenanceError(response.text)
    elif response.status_code == 500:
        raise CommentClient500Error(response.text)
    else:
        if raw:
            return response.text
        else:
            try:
                data = response.json()
            except ValueError:
                raise CommentClientError(
                    u"Invalid JSON response for request {request_id}; first 100 characters: '{content}'".format(
                        request_id=request_id,
                        content=response.text[:100]
                    )
                )
            if paged_results:
                dog_stats_api.histogram(
                    'comment_client.request.paged.result_count',
                    value=len(data.get('collection', [])),
                    tags=metric_tags
                )
                dog_stats_api.histogram(
                    'comment_client.request.paged.page',
                    value=data.get('page', 1),
                    tags=metric_tags
                )
                dog_stats_api.histogram(
                    'comment_client.request.paged.num_pages',
                    value=data.get('num_pages', 1),
                    tags=metric_tags
                )
            return data


class CommentClientError(Exception):
    pass


class CommentClientRequestError(CommentClientError):
    def __init__(self, msg, status_codes=400):
        super(CommentClientRequestError, self).__init__(msg)
        self.status_code = status_codes


class CommentClient500Error(CommentClientError):
    pass


class CommentClientMaintenanceError(CommentClientError):
    pass


class CommentClientPaginatedResult(object):
    """ class for paginated results returned from comment services"""

    def __init__(self, collection, page, num_pages, thread_count=0, corrected_text=None):
        self.collection = collection
        self.page = page
        self.num_pages = num_pages
        self.thread_count = thread_count
        self.corrected_text = corrected_text


def check_forum_heartbeat():
    """
    Check the forum connection via its built-in heartbeat service and create an answer which can be used in the LMS
    heartbeat django application.
    This function can be connected to the LMS heartbeat checker through the HEARTBEAT_CHECKS variable.
    """
    # To avoid dependency conflict
    from django_comment_common.models import ForumsConfig
    config = ForumsConfig.current()

    if not config.enabled:
        # If this check is enabled but forums disabled, don't connect, just report no error
        return 'forum', True, 'OK'

    try:
        res = requests.get(
            '%s/heartbeat' % COMMENTS_SERVICE,
            timeout=config.connection_timeout
        ).json()
        if res['OK']:
            return 'forum', True, 'OK'
        else:
            return 'forum', False, res.get('check', 'Forum heartbeat failed')
    except Exception as fail:
        return 'forum', False, unicode(fail)


def annotate_with_full_name(obj, user_id_field="user_id"):
    """Annotate an object with the author full name in place."""
    annotate_dict_with_full_name(obj.attributes, user_id_field=user_id_field)


def annotate_response_with_full_name(response):
    """Annotate API response with full name in place."""
    collection = response.get('collection', [])
    if collection:
        for record in collection:
            annotate_dict_with_full_name(record)


def annotate_dict_with_full_name(attributes, user_id_field="user_id"):
    """Annotate dict and all its children with user_full_name."""
    full_name = attributes.get("user_full_name")
    if not full_name:
        full_name = get_full_name(attributes.get(user_id_field))
        attributes["user_full_name"] = full_name

    child_keys = ["children", "endorsed_responses", "non_endorsed_responses"]

    for child_key in child_keys:
        children = attributes.get(child_key)
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            # All children objects have a "user_id" field, so we hardcode the value
            annotate_dict_with_full_name(child, user_id_field="user_id")


@request_cached
def get_full_name(user_id):
    """Return user's full name by its ID.

    The function uses the Django cache functionality to avoid hitting the database
    too often. The name is cached for 1 hour (3600 seconds), expires, but never
    gets invalidated.
    """
    from student.models import UserProfile

    if not user_id:
        return None

    cache_timeout = 3600
    cache_key = 'comment_client.get_full_name.v2.{}'.format(user_id)
    full_name = cache.get(cache_key)
    if is_not_found(full_name):
        return None

    if full_name is None:
        try:
            full_name = User.objects.get(id=user_id).profile.name
        except UserProfile.DoesNotExist:
            full_name = ""
        except User.DoesNotExist:
            full_name = UserNotFound()
        cache.set(cache_key, full_name, cache_timeout)

    if is_not_found(full_name):
        return None

    return full_name


class UserNotFound:
    """User not found sentinel.

    We store UserNotFound instances in the Redis cache instead of the username
    to avoid hitting the database when a user is not found."""
    pass


def is_not_found(value):
    """Return True if the object from the cache is a 'not found' sentinel."""
    return isinstance(value, UserNotFound)
