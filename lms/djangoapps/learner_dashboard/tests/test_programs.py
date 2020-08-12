# -*- coding: utf-8 -*-
"""
Unit tests covering the program listing and detail pages.
"""
import json
import re
from urlparse import urljoin
from uuid import uuid4

import mock
from bs4 import BeautifulSoup
from django.conf import settings
from django.urls import reverse, reverse_lazy
from django.test import override_settings

from lms.envs.test import CREDENTIALS_PUBLIC_SERVICE_URL
from openedx.core.djangoapps.catalog.constants import PathwayType
from openedx.core.djangoapps.catalog.tests.factories import (
    PathwayFactory,
    CourseFactory,
    CourseRunFactory,
    ProgramFactory
)
from openedx.core.djangoapps.catalog.tests.mixins import CatalogIntegrationMixin
from openedx.core.djangoapps.programs.tests.mixins import ProgramsApiConfigMixin
from openedx.core.djangolib.testing.utils import skip_unless_lms
from student.tests.factories import CourseEnrollmentFactory, UserFactory
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory as ModuleStoreCourseFactory

PROGRAMS_UTILS_MODULE = 'openedx.core.djangoapps.programs.utils'
PROGRAMS_MODULE = 'lms.djangoapps.learner_dashboard.programs'


def load_serialized_data(response, key):
    """
    Extract and deserialize serialized data from the response.
    """
    pattern = re.compile(r'{key}: (?P<data>\[.*\])'.format(key=key))
    match = pattern.search(response.content)
    serialized = match.group('data')

    return json.loads(serialized)


@skip_unless_lms
@override_settings(MKTG_URLS={'ROOT': 'https://www.example.com'})
@mock.patch(PROGRAMS_UTILS_MODULE + '.get_programs')
class TestProgramListing(ProgramsApiConfigMixin, SharedModuleStoreTestCase):
    """Unit tests for the program listing page."""
    shard = 4
    maxDiff = None
    password = 'test'
    url = reverse_lazy('program_listing_view')

    @classmethod
    def setUpClass(cls):
        super(TestProgramListing, cls).setUpClass()

        cls.course = ModuleStoreCourseFactory()
        course_run = CourseRunFactory(key=unicode(cls.course.id))
        course = CourseFactory(course_runs=[course_run])

        cls.first_program = ProgramFactory(courses=[course])
        cls.second_program = ProgramFactory(courses=[course])

        cls.data = sorted([cls.first_program, cls.second_program], key=cls.program_sort_key)

    def setUp(self):
        super(TestProgramListing, self).setUp()

        self.user = UserFactory()
        self.client.login(username=self.user.username, password=self.password)

    @classmethod
    def program_sort_key(cls, program):
        """
        Helper function used to sort dictionaries representing programs.
        """
        return program['title']

    def assert_dict_contains_subset(self, superset, subset):
        """
        Verify that the dict superset contains the dict subset.

        Works like assertDictContainsSubset, deprecated since Python 3.2.
        See: https://docs.python.org/2.7/library/unittest.html#unittest.TestCase.assertDictContainsSubset.
        """
        superset_keys = set(superset.keys())
        subset_keys = set(subset.keys())
        intersection = {key: superset[key] for key in superset_keys & subset_keys}

        self.assertEqual(subset, intersection)

    def test_login_required(self, mock_get_programs):
        """
        Verify that login is required to access the page.
        """
        self.create_programs_config()
        mock_get_programs.return_value = self.data

        self.client.logout()

        response = self.client.get(self.url)
        self.assertRedirects(
            response,
            '{}?next={}'.format(reverse('signin_user'), self.url)
        )

        self.client.login(username=self.user.username, password=self.password)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_404_if_disabled(self, _mock_get_programs):
        """
        Verify that the page 404s if disabled.
        """
        self.create_programs_config(enabled=False)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_empty_state(self, mock_get_programs):
        """
        Verify that the response contains no programs data when no programs are engaged.
        """
        self.create_programs_config()
        mock_get_programs.return_value = self.data

        response = self.client.get(self.url)
        self.assertContains(response, 'programsData: []')

    def test_programs_listed(self, mock_get_programs):
        """
        Verify that the response contains accurate programs data when programs are engaged.
        """
        self.create_programs_config()
        mock_get_programs.return_value = self.data

        CourseEnrollmentFactory(user=self.user, course_id=self.course.id)

        response = self.client.get(self.url)
        actual = load_serialized_data(response, 'programsData')
        actual = sorted(actual, key=self.program_sort_key)

        for index, actual_program in enumerate(actual):
            expected_program = self.data[index]
            self.assert_dict_contains_subset(actual_program, expected_program)

    def test_program_discovery(self, mock_get_programs):
        """
        Verify that a link to a programs marketing page appears in the response.
        """
        self.create_programs_config(marketing_path='bar')
        mock_get_programs.return_value = self.data

        marketing_root = urljoin(settings.MKTG_URLS.get('ROOT'), 'bar').rstrip('/')

        response = self.client.get(self.url)
        self.assertContains(response, marketing_root)

    def test_links_to_detail_pages(self, mock_get_programs):
        """
        Verify that links to detail pages are present.
        """
        self.create_programs_config()
        mock_get_programs.return_value = self.data

        CourseEnrollmentFactory(user=self.user, course_id=self.course.id)

        response = self.client.get(self.url)
        actual = load_serialized_data(response, 'programsData')
        actual = sorted(actual, key=self.program_sort_key)

        for index, actual_program in enumerate(actual):
            expected_program = self.data[index]

            expected_url = reverse('program_details_view', kwargs={'program_uuid': expected_program['uuid']})
            self.assertEqual(actual_program['detail_url'], expected_url)


@skip_unless_lms
@mock.patch(PROGRAMS_MODULE + '.get_pathways')
@mock.patch(PROGRAMS_UTILS_MODULE + '.get_programs')
class TestProgramDetails(ProgramsApiConfigMixin, CatalogIntegrationMixin, SharedModuleStoreTestCase):
    """Unit tests for the program details page."""
    shard = 4
    program_uuid = str(uuid4())
    password = 'test'
    url = reverse_lazy('program_details_view', kwargs={'program_uuid': program_uuid})

    @classmethod
    def setUpClass(cls):
        super(TestProgramDetails, cls).setUpClass()

        modulestore_course = ModuleStoreCourseFactory()
        course_run = CourseRunFactory(key=unicode(modulestore_course.id))
        course = CourseFactory(course_runs=[course_run])

        cls.program_data = ProgramFactory(uuid=cls.program_uuid, courses=[course])
        cls.pathway_data = PathwayFactory()
        cls.program_data['pathway_ids'] = [cls.pathway_data['id']]
        cls.pathway_data['program_uuids'] = [cls.program_data['uuid']]
        del cls.pathway_data['programs']

    def setUp(self):
        super(TestProgramDetails, self).setUp()

        self.user = UserFactory()
        self.client.login(username=self.user.username, password=self.password)

    def assert_program_data_present(self, response):
        """Verify that program data is present."""
        self.assertContains(response, 'programData')
        self.assertContains(response, 'urls')
        self.assertContains(response,
                            '"program_record_url": "{}/records/programs/'.format(CREDENTIALS_PUBLIC_SERVICE_URL))
        self.assertContains(response, 'program_listing_url')
        self.assertContains(response, self.program_data['title'])
        self.assert_programs_tab_present(response)

    def assert_programs_tab_present(self, response):
        """Verify that the programs tab is present in the nav."""
        soup = BeautifulSoup(response.content, 'html.parser')
        self.assertTrue(
            any(soup.find_all('a', class_='tab-nav-link', href=reverse('program_listing_view')))
        )

    def assert_pathway_data_present(self, response):
        """ Verify that the correct pathway data is present. """
        self.assertContains(response, 'industryPathways')
        self.assertContains(response, 'creditPathways')

        industry_pathways = load_serialized_data(response, 'industryPathways')
        credit_pathways = load_serialized_data(response, 'creditPathways')
        if self.pathway_data['pathway_type'] == PathwayType.CREDIT.value:
            credit_pathway, = credit_pathways  # Verify that there is only one credit pathway
            self.assertEqual(self.pathway_data, credit_pathway)
            self.assertEqual([], industry_pathways)
        elif self.pathway_data['pathway_type'] == PathwayType.INDUSTRY.value:
            industry_pathway, = industry_pathways  # Verify that there is only one industry pathway
            self.assertEqual(self.pathway_data, industry_pathway)
            self.assertEqual([], credit_pathways)

    def test_login_required(self, mock_get_programs, mock_get_pathways):
        """
        Verify that login is required to access the page.
        """
        self.create_programs_config()

        catalog_integration = self.create_catalog_integration()
        UserFactory(username=catalog_integration.service_username)

        mock_get_programs.return_value = self.program_data
        mock_get_pathways.return_value = self.pathway_data

        self.client.logout()

        response = self.client.get(self.url)
        self.assertRedirects(
            response,
            '{}?next={}'.format(reverse('signin_user'), self.url)
        )

        self.client.login(username=self.user.username, password=self.password)

        with mock.patch('lms.djangoapps.learner_dashboard.programs.get_certificates') as certs:
            certs.return_value = [{'type': 'program', 'url': '/'}]
            response = self.client.get(self.url)

        self.assert_program_data_present(response)
        self.assert_pathway_data_present(response)

    def test_404_if_disabled(self, _mock_get_programs, _mock_get_pathways):
        """
        Verify that the page 404s if disabled.
        """
        self.create_programs_config(enabled=False)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_404_if_no_data(self, mock_get_programs, _mock_get_pathways):
        """Verify that the page 404s if no program data is found."""
        self.create_programs_config()

        mock_get_programs.return_value = None

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
