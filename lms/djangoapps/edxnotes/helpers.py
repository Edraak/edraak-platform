"""
Helper methods related to EdxNotes.
"""
import json
import logging
import urlparse
from datetime import datetime
from json import JSONEncoder
from urllib import urlencode
from uuid import uuid4

import requests
from dateutil.parser import parse as dateutil_parse
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from django.utils.translation import ugettext as _
from opaque_keys.edx.keys import UsageKey
from provider.oauth2.models import Client
from requests.exceptions import RequestException

from courseware.access import has_access
from courseware.courses import get_current_child
from edxnotes.exceptions import EdxNotesParseError, EdxNotesServiceUnavailable
from edxnotes.plugins import EdxNotesTab
from lms.lib.utils import get_parent_unit
from openedx.core.djangoapps.oauth_dispatch.jwt import create_jwt_for_user
from student.models import anonymous_id_for_user
from util.date_utils import get_default_time_display
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError

log = logging.getLogger(__name__)
# OAuth2 Client name for edxnotes
CLIENT_NAME = "edx-notes"
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 25


class NoteJSONEncoder(JSONEncoder):
    """
    Custom JSON encoder that encode datetime objects to appropriate time strings.
    """
    # pylint: disable=method-hidden
    def default(self, obj):
        if isinstance(obj, datetime):
            return get_default_time_display(obj)
        return json.JSONEncoder.default(self, obj)


def get_edxnotes_id_token(user):
    """
    Returns generated ID Token for edxnotes.
    """
    # TODO: Use the system's JWT_AUDIENCE and JWT_SECRET_KEY instead of client ID and name.
    try:
        client = Client.objects.get(name=CLIENT_NAME)
    except Client.DoesNotExist:
        raise ImproperlyConfigured(
            'OAuth2 Client with name [{}] does not exist.'.format(CLIENT_NAME)
        )
    return create_jwt_for_user(user, secret=client.client_secret, aud=client.client_id)


def get_token_url(course_id):
    """
    Returns token url for the course.
    """
    return reverse("get_token", kwargs={
        "course_id": unicode(course_id),
    })


def send_request(user, course_id, page, page_size, path="", text=None):
    """
    Sends a request to notes api with appropriate parameters and headers.

    Arguments:
        user: Current logged in user
        course_id: Course id
        page: requested or default page number
        page_size: requested or default page size
        path: `search` or `annotations`. This is used to calculate notes api endpoint.
        text: text to search.

    Returns:
        Response received from notes api
    """
    url = get_internal_endpoint(path)
    params = {
        "user": anonymous_id_for_user(user, None),
        "course_id": unicode(course_id).encode("utf-8"),
        "page": page,
        "page_size": page_size,
    }

    if text:
        params.update({
            "text": text,
            "highlight": True
        })

    try:
        response = requests.get(
            url,
            headers={
                "x-annotator-auth-token": get_edxnotes_id_token(user)
            },
            params=params,
            timeout=(settings.EDXNOTES_CONNECT_TIMEOUT, settings.EDXNOTES_READ_TIMEOUT)
        )
    except RequestException:
        log.error("Failed to connect to edx-notes-api: url=%s, params=%s", url, str(params))
        raise EdxNotesServiceUnavailable(_("EdxNotes Service is unavailable. Please try again in a few minutes."))

    return response


def delete_all_notes_for_user(user):
    """
    helper method to delete all notes for a user, as part of GDPR compliance

    :param user: The user object associated with the deleted notes
    :return: response (requests) object

    Raises:
        EdxNotesServiceUnavailable - when notes api is not found/misconfigured.
    """
    url = get_internal_endpoint('retire_annotations')
    headers = {
        "x-annotator-auth-token": get_edxnotes_id_token(user),
    }
    data = {
        "user": anonymous_id_for_user(user, None)
    }
    try:
        response = requests.post(
            url=url,
            headers=headers,
            data=data,
            timeout=(settings.EDXNOTES_CONNECT_TIMEOUT, settings.EDXNOTES_READ_TIMEOUT)
        )
    except RequestException:
        log.error("Failed to connect to edx-notes-api: url=%s, params=%s", url, str(headers))
        raise EdxNotesServiceUnavailable(_("EdxNotes Service is unavailable. Please try again in a few minutes."))

    return response


def preprocess_collection(user, course, collection):
    """
    Prepare `collection(notes_list)` provided by edx-notes-api
    for rendering in a template:
       add information about ancestor blocks,
       convert "updated" to date

    Raises:
        ItemNotFoundError - when appropriate module is not found.
    """
    # pylint: disable=too-many-statements

    store = modulestore()
    filtered_collection = list()
    cache = {}
    include_path_info = ('course_structure' not in settings.NOTES_DISABLED_TABS)
    with store.bulk_operations(course.id):
        for model in collection:
            update = {
                u"updated": dateutil_parse(model["updated"]),
            }

            model.update(update)
            usage_id = model["usage_id"]
            if usage_id in cache:
                model.update(cache[usage_id])
                filtered_collection.append(model)
                continue

            usage_key = UsageKey.from_string(usage_id)
            # Add a course run if necessary.
            usage_key = usage_key.replace(course_key=store.fill_in_run(usage_key.course_key))

            try:
                item = store.get_item(usage_key)
            except ItemNotFoundError:
                log.debug("Module not found: %s", usage_key)
                continue

            if not has_access(user, "load", item, course_key=course.id):
                log.debug("User %s does not have an access to %s", user, item)
                continue

            unit = get_parent_unit(item)
            if unit is None:
                log.debug("Unit not found: %s", usage_key)
                continue

            if include_path_info:
                section = unit.get_parent()
                if not section:
                    log.debug("Section not found: %s", usage_key)
                    continue
                if section in cache:
                    usage_context = cache[section]
                    usage_context.update({
                        "unit": get_module_context(course, unit),
                    })
                    model.update(usage_context)
                    cache[usage_id] = cache[unit] = usage_context
                    filtered_collection.append(model)
                    continue

                chapter = section.get_parent()
                if not chapter:
                    log.debug("Chapter not found: %s", usage_key)
                    continue
                if chapter in cache:
                    usage_context = cache[chapter]
                    usage_context.update({
                        "unit": get_module_context(course, unit),
                        "section": get_module_context(course, section),
                    })
                    model.update(usage_context)
                    cache[usage_id] = cache[unit] = cache[section] = usage_context
                    filtered_collection.append(model)
                    continue

            usage_context = {
                "unit": get_module_context(course, unit),
                "section": get_module_context(course, section) if include_path_info else {},
                "chapter": get_module_context(course, chapter) if include_path_info else {},
            }
            model.update(usage_context)
            if include_path_info:
                cache[section] = cache[chapter] = usage_context

            cache[usage_id] = cache[unit] = usage_context
            filtered_collection.append(model)

    return filtered_collection


def get_module_context(course, item):
    """
    Returns dispay_name and url for the parent module.
    """
    item_dict = {
        'location': unicode(item.location),
        'display_name': item.display_name_with_default_escaped,
    }
    if item.category == 'chapter' and item.get_parent():
        # course is a locator w/o branch and version
        # so for uniformity we replace it with one that has them
        course = item.get_parent()
        item_dict['index'] = get_index(item_dict['location'], course.children)
    elif item.category == 'vertical':
        section = item.get_parent()
        chapter = section.get_parent()
        # Position starts from 1, that's why we add 1.
        position = get_index(unicode(item.location), section.children) + 1
        item_dict['url'] = reverse('courseware_position', kwargs={
            'course_id': unicode(course.id),
            'chapter': chapter.url_name,
            'section': section.url_name,
            'position': position,
        })
    if item.category in ('chapter', 'sequential'):
        item_dict['children'] = [unicode(child) for child in item.children]

    return item_dict


def get_index(usage_key, children):
    """
    Returns an index of the child with `usage_key`.
    """
    children = [unicode(child) for child in children]
    return children.index(usage_key)


def construct_pagination_urls(request, course_id, api_next_url, api_previous_url):
    """
    Construct next and previous urls for LMS. `api_next_url` and `api_previous_url`
    are returned from notes api but we need to transform them according to LMS notes
    views by removing and replacing extra information.

    Arguments:
        request: HTTP request object
        course_id: course id
        api_next_url: notes api next url
        api_previous_url: notes api previous url

    Returns:
        next_url: lms notes next url
        previous_url: lms notes previous url
    """
    def lms_url(url):
        """
        Create lms url from api url.
        """
        if url is None:
            return None

        keys = ('page', 'page_size', 'text')
        parsed = urlparse.urlparse(url)
        query_params = urlparse.parse_qs(parsed.query)

        encoded_query_params = urlencode({key: query_params.get(key)[0] for key in keys if key in query_params})
        return "{}?{}".format(request.build_absolute_uri(base_url), encoded_query_params)

    base_url = reverse("notes", kwargs={"course_id": course_id})
    next_url = lms_url(api_next_url)
    previous_url = lms_url(api_previous_url)

    return next_url, previous_url


def get_notes(request, course, page=DEFAULT_PAGE, page_size=DEFAULT_PAGE_SIZE, text=None):
    """
    Returns paginated list of notes for the user.

    Arguments:
        request: HTTP request object
        course: Course descriptor
        page: requested or default page number
        page_size: requested or default page size
        text: text to search. If None then return all results for the current logged in user.

    Returns:
        Paginated dictionary with these key:
            start: start of the current page
            current_page: current page number
            next: url for next page
            previous: url for previous page
            count: total number of notes available for the sent query
            num_pages: number of pages available
            results: list with notes info dictionary. each item in this list will be a dict
    """
    path = 'search' if text else 'annotations'
    response = send_request(request.user, course.id, page, page_size, path, text)

    try:
        collection = json.loads(response.content)
    except ValueError:
        log.error("Invalid JSON response received from notes api: response_content=%s", response.content)
        raise EdxNotesParseError(_("Invalid JSON response received from notes api."))

    # Verify response dict structure
    expected_keys = ['total', 'rows', 'num_pages', 'start', 'next', 'previous', 'current_page']
    keys = collection.keys()
    if not keys or not all(key in expected_keys for key in keys):
        log.error("Incorrect data received from notes api: collection_data=%s", str(collection))
        raise EdxNotesParseError(_("Incorrect data received from notes api."))

    filtered_results = preprocess_collection(request.user, course, collection['rows'])
    # Notes API is called from:
    # 1. The annotatorjs in courseware. It expects these attributes to be named "total" and "rows".
    # 2. The Notes tab Javascript proxied through LMS. It expects these attributes to be called "count" and "results".
    collection['count'] = collection['total']
    del collection['total']
    collection['results'] = filtered_results
    del collection['rows']

    collection['next'], collection['previous'] = construct_pagination_urls(
        request,
        course.id,
        collection['next'],
        collection['previous']
    )

    return collection


def get_endpoint(api_url, path=""):
    """
    Returns edx-notes-api endpoint.

    Arguments:
        api_url (str): base url to the notes api
        path (str): path to the resource
    Returns:
        str: full endpoint to the notes api
    """
    try:
        if not api_url.endswith("/"):
            api_url += "/"

        if path:
            if path.startswith("/"):
                path = path.lstrip("/")
            if not path.endswith("/"):
                path += "/"

        return api_url + path
    except (AttributeError, KeyError):
        raise ImproperlyConfigured(_("No endpoint was provided for EdxNotes."))


def get_public_endpoint(path=""):
    """Get the full path to a resource on the public notes API."""
    return get_endpoint(settings.EDXNOTES_PUBLIC_API, path)


def get_internal_endpoint(path=""):
    """Get the full path to a resource on the private notes API."""
    return get_endpoint(settings.EDXNOTES_INTERNAL_API, path)


def get_course_position(course_module):
    """
    Return the user's current place in the course.

    If this is the user's first time, leads to COURSE/CHAPTER/SECTION.
    If this isn't the users's first time, leads to COURSE/CHAPTER.

    If there is no current position in the course or chapter, then selects
    the first child.
    """
    urlargs = {'course_id': unicode(course_module.id)}
    chapter = get_current_child(course_module, min_depth=1)
    if chapter is None:
        log.debug("No chapter found when loading current position in course")
        return None

    urlargs['chapter'] = chapter.url_name
    if course_module.position is not None:
        return {
            'display_name': chapter.display_name_with_default_escaped,
            'url': reverse('courseware_chapter', kwargs=urlargs),
        }

    # Relying on default of returning first child
    section = get_current_child(chapter, min_depth=1)
    if section is None:
        log.debug("No section found when loading current position in course")
        return None

    urlargs['section'] = section.url_name
    return {
        'display_name': section.display_name_with_default_escaped,
        'url': reverse('courseware_section', kwargs=urlargs)
    }


def generate_uid():
    """
    Generates unique id.
    """
    return uuid4().int  # pylint: disable=no-member


def is_feature_enabled(course, user):
    """
    Returns True if Student Notes feature is enabled for the course, False otherwise.
    """
    return EdxNotesTab.is_enabled(course, user)
