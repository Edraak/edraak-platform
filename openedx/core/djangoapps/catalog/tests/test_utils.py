"""Tests covering utilities for integrating with the catalog service."""
# pylint: disable=missing-docstring

from datetime import timedelta

import mock
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.utils.timezone import now
from opaque_keys.edx.keys import CourseKey

from course_modes.helpers import CourseMode
from course_modes.tests.factories import CourseModeFactory
from entitlements.tests.factories import CourseEntitlementFactory
from openedx.core.constants import COURSE_UNPUBLISHED
from openedx.core.djangoapps.catalog.cache import (
    PATHWAY_CACHE_KEY_TPL,
    PROGRAM_CACHE_KEY_TPL,
    SITE_PATHWAY_IDS_CACHE_KEY_TPL,
    SITE_PROGRAM_UUIDS_CACHE_KEY_TPL
)
from openedx.core.djangoapps.catalog.models import CatalogIntegration
from openedx.core.djangoapps.catalog.tests.factories import (
    CourseFactory,
    CourseRunFactory,
    PathwayFactory,
    ProgramFactory,
    ProgramTypeFactory
)
from openedx.core.djangoapps.catalog.tests.mixins import CatalogIntegrationMixin
from openedx.core.djangoapps.catalog.utils import (
    get_course_runs,
    get_course_runs_for_course,
    get_course_run_details,
    get_currency_data,
    get_localized_price_text,
    get_owners_for_course,
    get_pathways,
    get_program_types,
    get_programs,
    get_visible_sessions_for_entitlement
)
from openedx.core.djangoapps.content.course_overviews.tests.factories import CourseOverviewFactory
from openedx.core.djangoapps.site_configuration.tests.factories import SiteFactory
from openedx.core.djangolib.testing.utils import CacheIsolationTestCase, skip_unless_lms
from student.tests.factories import CourseEnrollmentFactory, UserFactory

UTILS_MODULE = 'openedx.core.djangoapps.catalog.utils'
User = get_user_model()  # pylint: disable=invalid-name


@skip_unless_lms
@mock.patch(UTILS_MODULE + '.logger.info')
@mock.patch(UTILS_MODULE + '.logger.warning')
class TestGetPrograms(CacheIsolationTestCase):
    ENABLED_CACHES = ['default']

    def setUp(self):
        super(TestGetPrograms, self).setUp()
        self.site = SiteFactory()

    def test_get_many(self, mock_warning, mock_info):
        programs = ProgramFactory.create_batch(3)

        # Cache details for 2 of 3 programs.
        partial_programs = {
            PROGRAM_CACHE_KEY_TPL.format(uuid=program['uuid']): program for program in programs[:2]
        }
        cache.set_many(partial_programs, None)

        # When called before UUIDs are cached, the function should return an
        # empty list and log a warning.
        self.assertEqual(get_programs(self.site), [])
        mock_warning.assert_called_once_with(
            'Failed to get program UUIDs from the cache for site {}.'.format(self.site.domain)
        )
        mock_warning.reset_mock()

        # Cache UUIDs for all 3 programs.
        cache.set(
            SITE_PROGRAM_UUIDS_CACHE_KEY_TPL.format(domain=self.site.domain),
            [program['uuid'] for program in programs],
            None
        )

        actual_programs = get_programs(self.site)

        # The 2 cached programs should be returned while info and warning
        # messages should be logged for the missing one.
        self.assertEqual(
            set(program['uuid'] for program in actual_programs),
            set(program['uuid'] for program in partial_programs.values())
        )
        mock_info.assert_called_with('Failed to get details for 1 programs. Retrying.')
        mock_warning.assert_called_with(
            'Failed to get details for program {uuid} from the cache.'.format(uuid=programs[2]['uuid'])
        )
        mock_warning.reset_mock()

        # We can't use a set comparison here because these values are dictionaries
        # and aren't hashable. We've already verified that all programs came out
        # of the cache above, so all we need to do here is verify the accuracy of
        # the data itself.
        for program in actual_programs:
            key = PROGRAM_CACHE_KEY_TPL.format(uuid=program['uuid'])
            self.assertEqual(program, partial_programs[key])

        # Cache details for all 3 programs.
        all_programs = {
            PROGRAM_CACHE_KEY_TPL.format(uuid=program['uuid']): program for program in programs
        }
        cache.set_many(all_programs, None)

        actual_programs = get_programs(self.site)

        # All 3 programs should be returned.
        self.assertEqual(
            set(program['uuid'] for program in actual_programs),
            set(program['uuid'] for program in all_programs.values())
        )
        self.assertFalse(mock_warning.called)

        for program in actual_programs:
            key = PROGRAM_CACHE_KEY_TPL.format(uuid=program['uuid'])
            self.assertEqual(program, all_programs[key])

    @mock.patch(UTILS_MODULE + '.cache')
    def test_get_many_with_missing(self, mock_cache, mock_warning, mock_info):
        programs = ProgramFactory.create_batch(3)

        all_programs = {
            PROGRAM_CACHE_KEY_TPL.format(uuid=program['uuid']): program for program in programs
        }

        partial_programs = {
            PROGRAM_CACHE_KEY_TPL.format(uuid=program['uuid']): program for program in programs[:2]
        }

        def fake_get_many(keys):
            if len(keys) == 1:
                return {PROGRAM_CACHE_KEY_TPL.format(uuid=programs[-1]['uuid']): programs[-1]}
            else:
                return partial_programs

        mock_cache.get.return_value = [program['uuid'] for program in programs]
        mock_cache.get_many.side_effect = fake_get_many

        actual_programs = get_programs(self.site)

        # All 3 cached programs should be returned. An info message should be
        # logged about the one that was initially missing, but the code should
        # be able to stitch together all the details.
        self.assertEqual(
            set(program['uuid'] for program in actual_programs),
            set(program['uuid'] for program in all_programs.values())
        )
        self.assertFalse(mock_warning.called)
        mock_info.assert_called_with('Failed to get details for 1 programs. Retrying.')

        for program in actual_programs:
            key = PROGRAM_CACHE_KEY_TPL.format(uuid=program['uuid'])
            self.assertEqual(program, all_programs[key])

    def test_get_one(self, mock_warning, _mock_info):
        expected_program = ProgramFactory()
        expected_uuid = expected_program['uuid']

        self.assertEqual(get_programs(self.site, uuid=expected_uuid), None)
        mock_warning.assert_called_once_with(
            'Failed to get details for program {uuid} from the cache.'.format(uuid=expected_uuid)
        )
        mock_warning.reset_mock()

        cache.set(
            PROGRAM_CACHE_KEY_TPL.format(uuid=expected_uuid),
            expected_program,
            None
        )

        actual_program = get_programs(self.site, uuid=expected_uuid)
        self.assertEqual(actual_program, expected_program)
        self.assertFalse(mock_warning.called)


@skip_unless_lms
@mock.patch(UTILS_MODULE + '.logger.info')
@mock.patch(UTILS_MODULE + '.logger.warning')
class TestGetPathways(CacheIsolationTestCase):
    ENABLED_CACHES = ['default']

    def setUp(self):
        super(TestGetPathways, self).setUp()
        self.site = SiteFactory()

    def test_get_many(self, mock_warning, mock_info):
        pathways = PathwayFactory.create_batch(3)

        # Cache details for 2 of 3 programs.
        partial_pathways = {
            PATHWAY_CACHE_KEY_TPL.format(id=pathway['id']): pathway for pathway in pathways[:2]
        }
        cache.set_many(partial_pathways, None)

        # When called before pathways are cached, the function should return an
        # empty list and log a warning.
        self.assertEqual(get_pathways(self.site), [])
        mock_warning.assert_called_once_with('Failed to get credit pathway ids from the cache.')
        mock_warning.reset_mock()

        # Cache all 3 pathways
        cache.set(
            SITE_PATHWAY_IDS_CACHE_KEY_TPL.format(domain=self.site.domain),
            [pathway['id'] for pathway in pathways],
            None
        )

        actual_pathways = get_pathways(self.site)

        # The 2 cached pathways should be returned while info and warning
        # messages should be logged for the missing one.
        self.assertEqual(
            set(pathway['id'] for pathway in actual_pathways),
            set(pathway['id'] for pathway in partial_pathways.values())
        )
        mock_info.assert_called_with('Failed to get details for 1 pathways. Retrying.')
        mock_warning.assert_called_with(
            'Failed to get details for credit pathway {id} from the cache.'.format(id=pathways[2]['id'])
        )
        mock_warning.reset_mock()

        # We can't use a set comparison here because these values are dictionaries
        # and aren't hashable. We've already verified that all pathways came out
        # of the cache above, so all we need to do here is verify the accuracy of
        # the data itself.
        for pathway in actual_pathways:
            key = PATHWAY_CACHE_KEY_TPL.format(id=pathway['id'])
            self.assertEqual(pathway, partial_pathways[key])

        # Cache details for all 3 pathways.
        all_pathways = {
            PATHWAY_CACHE_KEY_TPL.format(id=pathway['id']): pathway for pathway in pathways
        }
        cache.set_many(all_pathways, None)

        actual_pathways = get_pathways(self.site)

        # All 3 pathways should be returned.
        self.assertEqual(
            set(pathway['id'] for pathway in actual_pathways),
            set(pathway['id'] for pathway in all_pathways.values())
        )
        self.assertFalse(mock_warning.called)

        for pathway in actual_pathways:
            key = PATHWAY_CACHE_KEY_TPL.format(id=pathway['id'])
            self.assertEqual(pathway, all_pathways[key])

    @mock.patch(UTILS_MODULE + '.cache')
    def test_get_many_with_missing(self, mock_cache, mock_warning, mock_info):
        pathways = PathwayFactory.create_batch(3)

        all_pathways = {
            PATHWAY_CACHE_KEY_TPL.format(id=pathway['id']): pathway for pathway in pathways
        }

        partial_pathways = {
            PATHWAY_CACHE_KEY_TPL.format(id=pathway['id']): pathway for pathway in pathways[:2]
        }

        def fake_get_many(keys):
            if len(keys) == 1:
                return {PATHWAY_CACHE_KEY_TPL.format(id=pathways[-1]['id']): pathways[-1]}
            else:
                return partial_pathways

        mock_cache.get.return_value = [pathway['id'] for pathway in pathways]
        mock_cache.get_many.side_effect = fake_get_many

        actual_pathways = get_pathways(self.site)

        # All 3 cached pathways should be returned. An info message should be
        # logged about the one that was initially missing, but the code should
        # be able to stitch together all the details.
        self.assertEqual(
            set(pathway['id'] for pathway in actual_pathways),
            set(pathway['id'] for pathway in all_pathways.values())
        )
        self.assertFalse(mock_warning.called)
        mock_info.assert_called_with('Failed to get details for 1 pathways. Retrying.')

        for pathway in actual_pathways:
            key = PATHWAY_CACHE_KEY_TPL.format(id=pathway['id'])
            self.assertEqual(pathway, all_pathways[key])

    def test_get_one(self, mock_warning, _mock_info):
        expected_pathway = PathwayFactory()
        expected_id = expected_pathway['id']

        self.assertEqual(get_pathways(self.site, pathway_id=expected_id), None)
        mock_warning.assert_called_once_with(
            'Failed to get details for credit pathway {id} from the cache.'.format(id=expected_id)
        )
        mock_warning.reset_mock()

        cache.set(
            PATHWAY_CACHE_KEY_TPL.format(id=expected_id),
            expected_pathway,
            None
        )

        actual_pathway = get_pathways(self.site, pathway_id=expected_id)
        self.assertEqual(actual_pathway, expected_pathway)
        self.assertFalse(mock_warning.called)


@mock.patch(UTILS_MODULE + '.get_edx_api_data')
class TestGetProgramTypes(CatalogIntegrationMixin, TestCase):
    """Tests covering retrieval of program types from the catalog service."""
    @override_settings(COURSE_CATALOG_API_URL='https://api.example.com/v1/')
    def test_get_program_types(self, mock_get_edx_api_data):
        """Verify get_program_types returns the expected list of program types."""
        program_types = ProgramTypeFactory.create_batch(3)
        mock_get_edx_api_data.return_value = program_types

        # Catalog integration is disabled.
        data = get_program_types()
        self.assertEqual(data, [])

        catalog_integration = self.create_catalog_integration()
        UserFactory(username=catalog_integration.service_username)
        data = get_program_types()
        self.assertEqual(data, program_types)

        program = program_types[0]
        data = get_program_types(name=program['name'])
        self.assertEqual(data, program)


@mock.patch(UTILS_MODULE + '.get_edx_api_data')
class TestGetCurrency(CatalogIntegrationMixin, TestCase):
    """Tests covering retrieval of currency data from the catalog service."""
    @override_settings(COURSE_CATALOG_API_URL='https://api.example.com/v1/')
    def test_get_currency_data(self, mock_get_edx_api_data):
        """Verify get_currency_data returns the currency data."""
        currency_data = {
            "code": "CAD",
            "rate": 1.257237,
            "symbol": "$"
        }
        mock_get_edx_api_data.return_value = currency_data

        # Catalog integration is disabled.
        data = get_currency_data()
        self.assertEqual(data, [])

        catalog_integration = self.create_catalog_integration()
        UserFactory(username=catalog_integration.service_username)
        data = get_currency_data()
        self.assertEqual(data, currency_data)


@mock.patch(UTILS_MODULE + '.get_currency_data')
class TestGetLocalizedPriceText(TestCase):
    """
    Tests covering converting prices to a localized currency
    """
    def test_localized_string(self, mock_get_currency_data):
        currency_data = {
            "BEL": {"rate": 0.835621, "code": "EUR", "symbol": u"\u20ac"},
            "GBR": {"rate": 0.737822, "code": "GBP", "symbol": u"\u00a3"},
            "CAN": {"rate": 2, "code": "CAD", "symbol": "$"},
        }
        mock_get_currency_data.return_value = currency_data

        request = RequestFactory().get('/dummy-url')
        request.session = {
            'country_code': 'CA'
        }
        expected_result = '$20 CAD'
        self.assertEqual(get_localized_price_text(10, request), expected_result)


@skip_unless_lms
@mock.patch(UTILS_MODULE + '.get_edx_api_data')
class TestGetCourseRuns(CatalogIntegrationMixin, TestCase):
    """
    Tests covering retrieval of course runs from the catalog service.
    """
    def setUp(self):
        super(TestGetCourseRuns, self).setUp()

        self.catalog_integration = self.create_catalog_integration(cache_ttl=1)
        self.user = UserFactory(username=self.catalog_integration.service_username)

    def assert_contract(self, call_args):
        """
        Verify that API data retrieval utility is used correctly.
        """
        args, kwargs = call_args

        for arg in (self.catalog_integration, 'course_runs'):
            self.assertIn(arg, args)

        self.assertEqual(kwargs['api']._store['base_url'], self.catalog_integration.get_internal_api_url())  # pylint: disable=protected-access

        querystring = {
            'page_size': 20,
            'exclude_utm': 1,
        }

        self.assertEqual(kwargs['querystring'], querystring)

        return args, kwargs

    def test_config_missing(self, mock_get_edx_api_data):
        """
        Verify that no errors occur when catalog config is missing.
        """
        CatalogIntegration.objects.all().delete()

        data = get_course_runs()
        self.assertFalse(mock_get_edx_api_data.called)
        self.assertEqual(data, [])

    @mock.patch(UTILS_MODULE + '.logger.error')
    def test_service_user_missing(self, mock_log_error, mock_get_edx_api_data):
        """
        Verify that no errors occur when the catalog service user is missing.
        """
        catalog_integration = self.create_catalog_integration(service_username='nonexistent-user')

        data = get_course_runs()
        mock_log_error.any_call(
            'Catalog service user with username [%s] does not exist. Course runs will not be retrieved.',
            catalog_integration.service_username,
        )
        self.assertFalse(mock_get_edx_api_data.called)
        self.assertEqual(data, [])

    def test_get_course_runs(self, mock_get_edx_api_data):
        """
        Test retrieval of course runs.
        """
        catalog_course_runs = CourseRunFactory.create_batch(10)
        mock_get_edx_api_data.return_value = catalog_course_runs

        data = get_course_runs()
        self.assertTrue(mock_get_edx_api_data.called)
        self.assert_contract(mock_get_edx_api_data.call_args)
        self.assertEqual(data, catalog_course_runs)

    def test_get_course_runs_by_course(self, mock_get_edx_api_data):
        """
        Test retrievals of run from a Course.
        """
        catalog_course_runs = CourseRunFactory.create_batch(10)
        catalog_course = CourseFactory(course_runs=catalog_course_runs)
        mock_get_edx_api_data.return_value = catalog_course

        data = get_course_runs_for_course(course_uuid=str(catalog_course['uuid']))
        self.assertTrue(mock_get_edx_api_data.called)
        self.assertEqual(data, catalog_course_runs)


@skip_unless_lms
@mock.patch(UTILS_MODULE + '.get_edx_api_data')
class TestGetCourseOwners(CatalogIntegrationMixin, TestCase):
    """
    Tests covering retrieval of course runs from the catalog service.
    """
    def setUp(self):
        super(TestGetCourseOwners, self).setUp()

        self.catalog_integration = self.create_catalog_integration(cache_ttl=1)
        self.user = UserFactory(username=self.catalog_integration.service_username)

    def test_get_course_owners_by_course(self, mock_get_edx_api_data):
        """
        Test retrieval of course runs.
        """
        catalog_course_runs = CourseRunFactory.create_batch(10)
        catalog_course = CourseFactory(course_runs=catalog_course_runs)
        mock_get_edx_api_data.return_value = catalog_course

        data = get_owners_for_course(course_uuid=str(catalog_course['uuid']))
        self.assertTrue(mock_get_edx_api_data.called)
        self.assertEqual(data, catalog_course['owners'])


@skip_unless_lms
@mock.patch(UTILS_MODULE + '.get_edx_api_data')
class TestSessionEntitlement(CatalogIntegrationMixin, TestCase):
    """
    Test Covering data related Entitlements.
    """
    def setUp(self):
        super(TestSessionEntitlement, self).setUp()

        self.catalog_integration = self.create_catalog_integration(cache_ttl=1)
        self.user = UserFactory(username=self.catalog_integration.service_username)
        self.tomorrow = now() + timedelta(days=1)

    def test_get_visible_sessions_for_entitlement(self, mock_get_edx_api_data):
        """
        Test retrieval of visible session entitlements.
        """
        catalog_course_run = CourseRunFactory.create()
        catalog_course = CourseFactory(course_runs=[catalog_course_run])
        mock_get_edx_api_data.return_value = catalog_course
        course_key = CourseKey.from_string(catalog_course_run.get('key'))
        course_overview = CourseOverviewFactory.create(id=course_key, start=self.tomorrow)
        CourseModeFactory.create(mode_slug=CourseMode.VERIFIED, min_price=100, course_id=course_overview.id)
        course_enrollment = CourseEnrollmentFactory(
            user=self.user, course_id=unicode(course_overview.id), mode=CourseMode.VERIFIED
        )
        entitlement = CourseEntitlementFactory(
            user=self.user, enrollment_course_run=course_enrollment, mode=CourseMode.VERIFIED
        )

        session_entitlements = get_visible_sessions_for_entitlement(entitlement)
        self.assertEqual(session_entitlements, [catalog_course_run])

    def test_get_visible_sessions_for_entitlement_expired_mode(self, mock_get_edx_api_data):
        """
        Test retrieval of visible session entitlements.
        """
        catalog_course_run = CourseRunFactory.create()
        catalog_course = CourseFactory(course_runs=[catalog_course_run])
        mock_get_edx_api_data.return_value = catalog_course
        course_key = CourseKey.from_string(catalog_course_run.get('key'))
        course_overview = CourseOverviewFactory.create(id=course_key, start=self.tomorrow)
        CourseModeFactory.create(
            mode_slug=CourseMode.VERIFIED,
            min_price=100,
            course_id=course_overview.id,
            expiration_datetime=now() - timedelta(days=1)
        )
        course_enrollment = CourseEnrollmentFactory(
            user=self.user, course_id=unicode(course_overview.id), mode=CourseMode.VERIFIED
        )
        entitlement = CourseEntitlementFactory(
            user=self.user, enrollment_course_run=course_enrollment, mode=CourseMode.VERIFIED
        )

        session_entitlements = get_visible_sessions_for_entitlement(entitlement)
        self.assertEqual(session_entitlements, [catalog_course_run])

    def test_unpublished_sessions_for_entitlement_when_enrolled(self, mock_get_edx_api_data):
        """
        Test unpublished course runs are part of visible session entitlements when the user
        is enrolled.
        """
        catalog_course_run = CourseRunFactory.create(status=COURSE_UNPUBLISHED)
        catalog_course = CourseFactory(course_runs=[catalog_course_run])
        mock_get_edx_api_data.return_value = catalog_course
        course_key = CourseKey.from_string(catalog_course_run.get('key'))
        course_overview = CourseOverviewFactory.create(id=course_key, start=self.tomorrow)
        CourseModeFactory.create(
            mode_slug=CourseMode.VERIFIED,
            min_price=100,
            course_id=course_overview.id,
            expiration_datetime=now() - timedelta(days=1)
        )
        course_enrollment = CourseEnrollmentFactory(
            user=self.user, course_id=unicode(course_overview.id), mode=CourseMode.VERIFIED
        )
        entitlement = CourseEntitlementFactory(
            user=self.user, enrollment_course_run=course_enrollment, mode=CourseMode.VERIFIED
        )

        session_entitlements = get_visible_sessions_for_entitlement(entitlement)
        self.assertEqual(session_entitlements, [catalog_course_run])

    def test_unpublished_sessions_for_entitlement(self, mock_get_edx_api_data):
        """
        Test unpublished course runs are not part of visible session entitlements when the user
        is not enrolled.
        """
        catalog_course_run = CourseRunFactory.create(status=COURSE_UNPUBLISHED)
        catalog_course = CourseFactory(course_runs=[catalog_course_run])
        mock_get_edx_api_data.return_value = catalog_course
        course_key = CourseKey.from_string(catalog_course_run.get('key'))
        course_overview = CourseOverviewFactory.create(id=course_key, start=self.tomorrow)
        CourseModeFactory.create(mode_slug=CourseMode.VERIFIED, min_price=100, course_id=course_overview.id)
        entitlement = CourseEntitlementFactory(
            user=self.user, mode=CourseMode.VERIFIED
        )

        session_entitlements = get_visible_sessions_for_entitlement(entitlement)
        self.assertEqual(session_entitlements, [])


@skip_unless_lms
@mock.patch(UTILS_MODULE + '.get_edx_api_data')
class TestGetCourseRunDetails(CatalogIntegrationMixin, TestCase):
    """
    Tests covering retrieval of information about a specific course run from the catalog service.
    """
    def setUp(self):
        super(TestGetCourseRunDetails, self).setUp()
        self.catalog_integration = self.create_catalog_integration(cache_ttl=1)
        self.user = UserFactory(username=self.catalog_integration.service_username)

    def test_get_course_run_details(self, mock_get_edx_api_data):
        """
        Test retrieval of details about a specific course run
        """
        course_run = CourseRunFactory()
        course_run_details = {
            'content_language': course_run['content_language'],
            'weeks_to_complete': course_run['weeks_to_complete'],
            'max_effort': course_run['max_effort']
        }
        mock_get_edx_api_data.return_value = course_run_details
        data = get_course_run_details(course_run['key'], ['content_language', 'weeks_to_complete', 'max_effort'])
        self.assertTrue(mock_get_edx_api_data.called)
        self.assertEqual(data, course_run_details)
