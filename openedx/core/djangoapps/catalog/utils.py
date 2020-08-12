"""Helper functions for working with the catalog service."""
import copy
import datetime
import logging
import uuid

import pycountry
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from edx_rest_api_client.client import EdxRestApiClient
from opaque_keys.edx.keys import CourseKey
from pytz import UTC

from entitlements.utils import is_course_run_entitlement_fulfillable
from openedx.core.constants import COURSE_PUBLISHED
from openedx.core.djangoapps.catalog.cache import (PATHWAY_CACHE_KEY_TPL, PROGRAM_CACHE_KEY_TPL,
                                                   SITE_PATHWAY_IDS_CACHE_KEY_TPL,
                                                   SITE_PROGRAM_UUIDS_CACHE_KEY_TPL)
from openedx.core.djangoapps.catalog.models import CatalogIntegration
from openedx.core.djangoapps.oauth_dispatch.jwt import create_jwt_for_user
from openedx.core.lib.edx_api_utils import get_edx_api_data
from student.models import CourseEnrollment

logger = logging.getLogger(__name__)


def create_catalog_api_client(user, site=None):
    """Returns an API client which can be used to make Catalog API requests."""
    jwt = create_jwt_for_user(user)

    if site:
        url = site.configuration.get_value('COURSE_CATALOG_API_URL')
    else:
        url = CatalogIntegration.current().get_internal_api_url()

    return EdxRestApiClient(url, jwt=jwt)


def check_catalog_integration_and_get_user(error_message_field):
    """
    Checks that catalog integration is enabled, and if so, attempts to get and
    return the service user.

    Parameters:
        error_message_field (str): The field that will be attempted to be
            retrieved when calling the api client. Used for the error message.

    Returns:
        Tuple of:
            The catalog integration service user if it exists, else None
            The catalog integration Object
                Note: (This is necessary for future calls of functions using this method)
    """
    catalog_integration = CatalogIntegration.current()

    if catalog_integration.is_enabled():
        try:
            user = catalog_integration.get_service_user()
        except ObjectDoesNotExist:
            logger.error(
                'Catalog service user with username [{username}] does not exist. '
                '{field} will not be retrieved.'.format(
                    username=catalog_integration.service_username,
                    field=error_message_field,
                )
            )
            return None, catalog_integration
        return user, catalog_integration
    else:
        logger.error(
            'Unable to retrieve details about {field} because Catalog Integration is not enabled'.format(
                field=error_message_field,
            )
        )
        return None, catalog_integration


def get_programs(site, uuid=None):
    """Read programs from the cache.

    The cache is populated by a management command, cache_programs.

    Arguments:
        site (Site): django.contrib.sites.models object

    Keyword Arguments:
        uuid (string): UUID identifying a specific program to read from the cache.

    Returns:
        list of dict, representing programs.
        dict, if a specific program is requested.
    """
    missing_details_msg_tpl = 'Failed to get details for program {uuid} from the cache.'

    if uuid:
        program = cache.get(PROGRAM_CACHE_KEY_TPL.format(uuid=uuid))
        if not program:
            logger.warning(missing_details_msg_tpl.format(uuid=uuid))

        return program
    uuids = cache.get(SITE_PROGRAM_UUIDS_CACHE_KEY_TPL.format(domain=site.domain), [])
    if not uuids:
        logger.warning('Failed to get program UUIDs from the cache for site {}.'.format(site.domain))

    programs = cache.get_many([PROGRAM_CACHE_KEY_TPL.format(uuid=uuid) for uuid in uuids])
    programs = list(programs.values())

    # The get_many above sometimes fails to bring back details cached on one or
    # more Memcached nodes. It doesn't look like these keys are being evicted.
    # 99% of the time all keys come back, but 1% of the time all the keys stored
    # on one or more nodes are missing from the result of the get_many. One
    # get_many may fail to bring these keys back, but a get_many occurring
    # immediately afterwards will succeed in bringing back all the keys. This
    # behavior can be mitigated by trying again for the missing keys, which is
    # what we do here. Splitting the get_many into smaller chunks may also help.
    missing_uuids = set(uuids) - set(program['uuid'] for program in programs)
    if missing_uuids:
        logger.info(
            'Failed to get details for {count} programs. Retrying.'.format(count=len(missing_uuids))
        )

        retried_programs = cache.get_many([PROGRAM_CACHE_KEY_TPL.format(uuid=uuid) for uuid in missing_uuids])
        programs += list(retried_programs.values())

        still_missing_uuids = set(uuids) - set(program['uuid'] for program in programs)
        for uuid in still_missing_uuids:
            logger.warning(missing_details_msg_tpl.format(uuid=uuid))

    return programs


def get_program_types(name=None):
    """Retrieve program types from the catalog service.

    Keyword Arguments:
        name (string): Name identifying a specific program.

    Returns:
        list of dict, representing program types.
        dict, if a specific program type is requested.
    """
    user, catalog_integration = check_catalog_integration_and_get_user(error_message_field='Program types')
    if user:
        api = create_catalog_api_client(user)
        cache_key = '{base}.program_types'.format(base=catalog_integration.CACHE_KEY)

        data = get_edx_api_data(catalog_integration, 'program_types', api=api,
                                cache_key=cache_key if catalog_integration.is_cache_enabled else None)

        # Filter by name if a name was provided
        if name:
            data = next(program_type for program_type in data if program_type['name'] == name)

        return data
    else:
        return []


def get_pathways(site, pathway_id=None):
    """
    Read pathways from the cache.
    The cache is populated by a management command, cache_programs.

    Arguments:
        site (Site): django.contrib.sites.models object

    Keyword Arguments:
        pathway_id (string): id identifying a specific pathway to read from the cache.

    Returns:
        list of dict, representing pathways.
        dict, if a specific pathway is requested.
    """
    missing_details_msg_tpl = 'Failed to get details for credit pathway {id} from the cache.'

    if pathway_id:
        pathway = cache.get(PATHWAY_CACHE_KEY_TPL.format(id=pathway_id))
        if not pathway:
            logger.warning(missing_details_msg_tpl.format(id=pathway_id))

        return pathway
    pathway_ids = cache.get(SITE_PATHWAY_IDS_CACHE_KEY_TPL.format(domain=site.domain), [])
    if not pathway_ids:
        logger.warning('Failed to get credit pathway ids from the cache.')

    pathways = cache.get_many([PATHWAY_CACHE_KEY_TPL.format(id=pathway_id) for pathway_id in pathway_ids])
    pathways = pathways.values()

    # The get_many above sometimes fails to bring back details cached on one or
    # more Memcached nodes. It doesn't look like these keys are being evicted.
    # 99% of the time all keys come back, but 1% of the time all the keys stored
    # on one or more nodes are missing from the result of the get_many. One
    # get_many may fail to bring these keys back, but a get_many occurring
    # immediately afterwards will succeed in bringing back all the keys. This
    # behavior can be mitigated by trying again for the missing keys, which is
    # what we do here. Splitting the get_many into smaller chunks may also help.
    missing_ids = set(pathway_ids) - set(pathway['id'] for pathway in pathways)
    if missing_ids:
        logger.info(
            'Failed to get details for {count} pathways. Retrying.'.format(count=len(missing_ids))
        )

        retried_pathways = cache.get_many(
            [PATHWAY_CACHE_KEY_TPL.format(id=pathway_id) for pathway_id in missing_ids]
        )
        pathways += retried_pathways.values()

        still_missing_ids = set(pathway_ids) - set(pathway['id'] for pathway in pathways)
        for missing_id in still_missing_ids:
            logger.warning(missing_details_msg_tpl.format(id=missing_id))

    return pathways


def get_currency_data():
    """Retrieve currency data from the catalog service.

    Returns:
        list of dict, representing program types.
        dict, if a specific program type is requested.
    """
    user, catalog_integration = check_catalog_integration_and_get_user(error_message_field='Currency data')
    if user:
        api = create_catalog_api_client(user)
        cache_key = '{base}.currency'.format(base=catalog_integration.CACHE_KEY)

        return get_edx_api_data(catalog_integration, 'currency', api=api, traverse_pagination=False,
                                cache_key=cache_key if catalog_integration.is_cache_enabled else None)
    else:
        return []


def format_price(price, symbol='$', code='USD'):
    """
    Format the price to have the appropriate currency and digits..

    :param price: The price amount.
    :param symbol: The symbol for the price (default: $)
    :param code: The currency code to be appended to the price (default: USD)
    :return: A formatted price string, i.e. '$10 USD', '$10.52 USD'.
    """
    if int(price) == price:
        return '{}{} {}'.format(symbol, int(price), code)
    return '{}{:0.2f} {}'.format(symbol, price, code)


def get_localized_price_text(price, request):
    """
    Returns the localized converted price as string (ex. '$150 USD')

    If the users location has been added to the request, this will return the given price based on conversion rate
    from the Catalog service and return a localized string otherwise will return the default price in USD
    """
    user_currency = {
        'symbol': '$',
        'rate': 1,
        'code': 'USD'
    }

    # session.country_code is added via CountryMiddleware in the LMS
    user_location = getattr(request, 'session', {}).get('country_code')

    # Override default user_currency if location is available
    if user_location and get_currency_data:
        currency_data = get_currency_data()
        user_country = pycountry.countries.get(alpha2=user_location)
        user_currency = currency_data.get(user_country.alpha3, user_currency)

    return format_price(
        price=(price * user_currency['rate']),
        symbol=user_currency['symbol'],
        code=user_currency['code']
    )


def get_programs_with_type(site, include_hidden=True):
    """
    Return the list of programs. You can filter the types of programs returned by using the optional
    include_hidden parameter. By default hidden programs will be included.

    The program dict is updated with the fully serialized program type.

    Arguments:
        site (Site): django.contrib.sites.models object

    Keyword Arguments:
        include_hidden (bool): whether to include hidden programs

    Return:
        list of dict, representing the active programs.
    """
    programs_with_type = []
    programs = get_programs(site)

    if programs:
        program_types = {program_type['name']: program_type for program_type in get_program_types()}
        for program in programs:
            if program['type'] not in program_types:
                continue

            if program['hidden'] and not include_hidden:
                continue

            # deepcopy the program dict here so we are not adding
            # the type to the cached object
            program_with_type = copy.deepcopy(program)
            program_with_type['type'] = program_types[program['type']]
            programs_with_type.append(program_with_type)

    return programs_with_type


def get_course_runs():
    """
    Retrieve all the course runs from the catalog service.

    Returns:
        list of dict with each record representing a course run.
    """
    course_runs = []
    user, catalog_integration = check_catalog_integration_and_get_user(error_message_field='Course runs')
    if user:
        api = create_catalog_api_client(user)

        querystring = {
            'page_size': catalog_integration.page_size,
            'exclude_utm': 1,
        }

        course_runs = get_edx_api_data(catalog_integration, 'course_runs', api=api, querystring=querystring)

    return course_runs


def get_course_runs_for_course(course_uuid):
    user, catalog_integration = check_catalog_integration_and_get_user(error_message_field='Course runs')
    if user:
        api = create_catalog_api_client(user)
        cache_key = '{base}.course.{uuid}.course_runs'.format(
            base=catalog_integration.CACHE_KEY,
            uuid=course_uuid
        )
        data = get_edx_api_data(
            catalog_integration,
            'courses',
            resource_id=course_uuid,
            api=api,
            cache_key=cache_key if catalog_integration.is_cache_enabled else None,
            long_term_cache=True,
            many=False
        )
        return data.get('course_runs', [])
    else:
        return []


def get_owners_for_course(course_uuid):
    user, catalog_integration = check_catalog_integration_and_get_user(error_message_field='Owners')
    if user:
        api = create_catalog_api_client(user)
        cache_key = '{base}.course.{uuid}.course_runs'.format(
            base=catalog_integration.CACHE_KEY,
            uuid=course_uuid
        )
        data = get_edx_api_data(
            catalog_integration,
            'courses',
            resource_id=course_uuid,
            api=api,
            cache_key=cache_key if catalog_integration.is_cache_enabled else None,
            long_term_cache=True,
            many=False
        )
        return data.get('owners', [])
    else:
        return []


def get_course_uuid_for_course(course_run_key):
    """
    Retrieve the Course UUID for a given course key

    Arguments:
        course_run_key (CourseKey): A Key for a Course run that will be pulled apart to get just the information
        required for a Course (e.g. org+course)

    Returns:
        UUID: Course UUID and None if it was not retrieved.
    """
    user, catalog_integration = check_catalog_integration_and_get_user(error_message_field='Course UUID')
    if user:
        api = create_catalog_api_client(user)

        run_cache_key = '{base}.course_run.{course_run_key}'.format(
            base=catalog_integration.CACHE_KEY,
            course_run_key=course_run_key
        )

        course_run_data = get_edx_api_data(
            catalog_integration,
            'course_runs',
            resource_id=unicode(course_run_key),
            api=api,
            cache_key=run_cache_key if catalog_integration.is_cache_enabled else None,
            long_term_cache=True,
            many=False,
        )

        course_key_str = course_run_data.get('course', None)

        if course_key_str:
            run_cache_key = '{base}.course.{course_key}'.format(
                base=catalog_integration.CACHE_KEY,
                course_key=course_key_str
            )

            data = get_edx_api_data(
                catalog_integration,
                'courses',
                resource_id=course_key_str,
                api=api,
                cache_key=run_cache_key if catalog_integration.is_cache_enabled else None,
                long_term_cache=True,
                many=False,
            )
            uuid_str = data.get('uuid', None)
            if uuid_str:
                return uuid.UUID(uuid_str)
    return None


def get_pseudo_session_for_entitlement(entitlement):
    """
    This function is used to pass pseudo-data to the front end, returning a single session, regardless of whether that
    session is currently available.

    First tries to return the first available session, followed by the first session regardless of availability.
    Returns None if there are no sessions for that course.
    """
    sessions_for_course = get_course_runs_for_course(entitlement.course_uuid)
    available_sessions = get_fulfillable_course_runs_for_entitlement(entitlement, sessions_for_course)
    if available_sessions:
        return available_sessions[0]
    if sessions_for_course:
        return sessions_for_course[0]
    return None


def get_visible_sessions_for_entitlement(entitlement):
    """
    Takes an entitlement object and returns the course runs that a user can currently enroll in.
    """
    sessions_for_course = get_course_runs_for_course(entitlement.course_uuid)
    return get_fulfillable_course_runs_for_entitlement(entitlement, sessions_for_course)


def get_fulfillable_course_runs_for_entitlement(entitlement, course_runs):
    """
    Looks through the list of course runs and returns the course runs that can
    be applied to the entitlement.

    Args:
        entitlement (CourseEntitlement): The CourseEntitlement to which a
        course run is to be applied.
        course_runs (list): List of course run that we would like to apply
        to the entitlement.

    Return:
        list: A list of sessions that a user can apply to the provided entitlement.
    """
    enrollable_sessions = []

    # Only retrieve list of published course runs that can still be enrolled and upgraded
    search_time = datetime.datetime.now(UTC)
    for course_run in course_runs:
        course_id = CourseKey.from_string(course_run.get('key'))
        (user_enrollment_mode, is_active) = CourseEnrollment.enrollment_mode_for_user(
            user=entitlement.user,
            course_id=course_id
        )
        is_enrolled_in_mode = is_active and (user_enrollment_mode == entitlement.mode)
        if (is_enrolled_in_mode and
                entitlement.enrollment_course_run and
                course_id == entitlement.enrollment_course_run.course_id):
            # User is enrolled in the course so we should include it in the list of enrollable sessions always
            # this will ensure it is available for the UI
            enrollable_sessions.append(course_run)
        elif (course_run.get('status') == COURSE_PUBLISHED and not
              is_enrolled_in_mode and
              is_course_run_entitlement_fulfillable(course_id, entitlement, search_time)):
                enrollable_sessions.append(course_run)

    enrollable_sessions.sort(key=lambda session: session.get('start'))
    return enrollable_sessions


def get_course_run_details(course_run_key, fields):
    """
    Retrieve information about the course run with the given id

    Arguments:
        course_run_key: key for the course_run about which we are retrieving information

    Returns:
        dict with language, start date, end date, and max_effort details about specified course run
    """
    course_run_details = dict()
    user, catalog_integration = check_catalog_integration_and_get_user(
        error_message_field='Data for course_run {}'.format(course_run_key)
    )
    if user:
        api = create_catalog_api_client(user)

        cache_key = '{base}.course_runs'.format(base=catalog_integration.CACHE_KEY)

        course_run_details = get_edx_api_data(catalog_integration, 'course_runs', api, resource_id=course_run_key,
                                              cache_key=cache_key, many=False, traverse_pagination=False, fields=fields)
    return course_run_details
