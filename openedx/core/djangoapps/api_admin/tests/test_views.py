""" Tests for the api_admin app's views. """

import json

import ddt
import httpretty
from django.conf import settings
from django.urls import reverse
from django.test import TestCase
from django.test.utils import override_settings
from oauth2_provider.models import get_application_model

from openedx.core.djangoapps.api_admin.models import ApiAccessConfig, ApiAccessRequest
from openedx.core.djangoapps.api_admin.tests.factories import (
    ApiAccessRequestFactory,
    ApplicationFactory,
    CatalogFactory
)
from openedx.core.djangoapps.api_admin.tests.utils import VALID_DATA
from openedx.core.djangolib.testing.utils import skip_unless_lms
from student.tests.factories import UserFactory

Application = get_application_model()  # pylint: disable=invalid-name


class ApiAdminTest(TestCase):
    """
    Base class to allow API admin access to tests.
    """
    def setUp(self):
        super(ApiAdminTest, self).setUp()
        ApiAccessConfig(enabled=True).save()


@skip_unless_lms
class ApiRequestViewTest(ApiAdminTest):
    """
    Test the API Request View.
    """
    def setUp(self):
        super(ApiRequestViewTest, self).setUp()
        self.url = reverse('api_admin:api-request')
        password = 'abc123'
        self.user = UserFactory(password=password)
        self.client.login(username=self.user.username, password=password)

    def test_get(self):
        """Verify that a logged-in can see the API request form."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_get_anonymous(self):
        """Verify that users must be logged in to see the page."""
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_get_with_existing_request(self):
        """
        Verify that users who have already requested access are redirected
        to the client creation page to see their status.
        """
        ApiAccessRequestFactory(user=self.user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('api_admin:api-status'))

    def _assert_post_success(self, response):
        """
        Assert that a successful POST has been made, that the response
        redirects correctly, and that the correct object has been created.
        """
        self.assertRedirects(response, reverse('api_admin:api-status'))
        api_request = ApiAccessRequest.objects.get(user=self.user)
        self.assertEqual(api_request.status, ApiAccessRequest.PENDING)
        return api_request

    def test_post_valid(self):
        """Verify that a logged-in user can create an API request."""
        self.assertFalse(ApiAccessRequest.objects.all().exists())
        response = self.client.post(self.url, VALID_DATA)
        self._assert_post_success(response)

    def test_post_anonymous(self):
        """Verify that users must be logged in to create an access request."""
        self.client.logout()
        response = self.client.post(self.url, VALID_DATA)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ApiAccessRequest.objects.all().exists())

    def test_get_with_feature_disabled(self):
        """Verify that the view can be disabled via ApiAccessConfig."""
        ApiAccessConfig(enabled=False).save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_post_with_feature_disabled(self):
        """Verify that the view can be disabled via ApiAccessConfig."""
        ApiAccessConfig(enabled=False).save()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 404)


@skip_unless_lms
@override_settings(PLATFORM_NAME='edX')
@ddt.ddt
class ApiRequestStatusViewTest(ApiAdminTest):
    """
    Tests of the API Status endpoint.
    """
    def setUp(self):
        super(ApiRequestStatusViewTest, self).setUp()
        password = 'abc123'
        self.user = UserFactory(password=password)
        self.client.login(username=self.user.username, password=password)
        self.url = reverse('api_admin:api-status')

    def test_get_without_request(self):
        """
        Verify that users who have not yet requested API access are
        redirected to the API request form.
        """
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('api_admin:api-request'))

    @ddt.data(
        (ApiAccessRequest.APPROVED, 'Your request to access the edX Course Catalog API has been approved.'),
        (ApiAccessRequest.PENDING, 'Your request to access the edX Course Catalog API is being processed.'),
        (ApiAccessRequest.DENIED, 'Your request to access the edX Course Catalog API has been denied.'),
    )
    @ddt.unpack
    def test_get_with_request(self, status, expected):
        """
        Verify that users who have requested access can see a message
        regarding their request status.
        """
        ApiAccessRequestFactory(user=self.user, status=status)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(expected, response.content)

    def test_get_with_existing_application(self):
        """
        Verify that if the user has created their client credentials, they
        are shown on the status page.
        """
        ApiAccessRequestFactory(user=self.user, status=ApiAccessRequest.APPROVED)
        application = ApplicationFactory(user=self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        unicode_content = response.content.decode('utf-8')
        self.assertIn(application.client_secret, unicode_content)
        self.assertIn(application.client_id, unicode_content)
        self.assertIn(application.redirect_uris, unicode_content)

    def test_get_anonymous(self):
        """Verify that users must be logged in to see the page."""
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_get_with_feature_disabled(self):
        """Verify that the view can be disabled via ApiAccessConfig."""
        ApiAccessConfig(enabled=False).save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    @ddt.data(
        (ApiAccessRequest.APPROVED, True, True),
        (ApiAccessRequest.DENIED, True, False),
        (ApiAccessRequest.PENDING, True, False),
        (ApiAccessRequest.APPROVED, False, True),
        (ApiAccessRequest.DENIED, False, False),
        (ApiAccessRequest.PENDING, False, False),
    )
    @ddt.unpack
    def test_post(self, status, application_exists, new_application_created):
        """
        Verify that posting the form creates an application if the user is
        approved, and does not otherwise. Also ensure that if the user
        already has an application, it is deleted before a new
        application is created.
        """
        if application_exists:
            old_application = ApplicationFactory(user=self.user)
        ApiAccessRequestFactory(user=self.user, status=status)
        self.client.post(self.url, {
            'name': 'test.com',
            'redirect_uris': 'http://example.com'
        })
        applications = Application.objects.filter(user=self.user)
        if application_exists and new_application_created:
            self.assertEqual(applications.count(), 1)
            self.assertNotEqual(old_application, applications[0])
        elif application_exists:
            self.assertEqual(applications.count(), 1)
            self.assertEqual(old_application, applications[0])
        elif new_application_created:
            self.assertEqual(applications.count(), 1)
        else:
            self.assertEqual(applications.count(), 0)

    def test_post_with_errors(self):
        ApiAccessRequestFactory(user=self.user, status=ApiAccessRequest.APPROVED)
        response = self.client.post(self.url, {
            'name': 'test.com',
            'redirect_uris': 'not a url'
        })
        self.assertIn('Enter a valid URL.', response.content)


@skip_unless_lms
class ApiTosViewTest(ApiAdminTest):
    """
    Tests of the API terms of service endpoint.
    """
    def test_get_api_tos(self):
        """
        Verify that the terms of service can be read.
        """
        url = reverse('api_admin:api-tos')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Terms of Service', response.content)


class CatalogTest(ApiAdminTest):
    """
    Test the catalog API.
    """
    def setUp(self):
        super(CatalogTest, self).setUp()
        password = 'abc123'
        self.user = UserFactory(password=password, is_staff=True)
        self.client.login(username=self.user.username, password=password)

    def mock_catalog_endpoint(self, data, catalog_id=None, method=httpretty.GET, status_code=200):
        """ Mock the Course Catalog API's catalog endpoint. """
        self.assertTrue(httpretty.is_enabled(), msg='httpretty must be enabled to mock Catalog API calls.')

        url = '{root}/catalogs/'.format(root=settings.COURSE_CATALOG_API_URL.rstrip('/'))
        if catalog_id:
            url += '{id}/'.format(id=catalog_id)

        httpretty.register_uri(
            method,
            url,
            body=json.dumps(data),
            content_type='application/json',
            status=status_code
        )


@skip_unless_lms
class CatalogSearchViewTest(CatalogTest):
    """
    Test the catalog search endpoint.
    """
    def setUp(self):
        super(CatalogSearchViewTest, self).setUp()
        self.url = reverse('api_admin:catalog-search')

    def test_get(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    @httpretty.activate
    def test_post(self):
        catalog_user = UserFactory()
        self.mock_catalog_endpoint({'results': []})
        response = self.client.post(self.url, {'username': catalog_user.username})
        self.assertRedirects(response, reverse('api_admin:catalog-list', kwargs={'username': catalog_user.username}))

    def test_post_without_username(self):
        response = self.client.post(self.url, {'username': ''})
        self.assertRedirects(response, reverse('api_admin:catalog-search'))


@skip_unless_lms
class CatalogListViewTest(CatalogTest):
    """
    Test the catalog list endpoint.
    """
    def setUp(self):
        super(CatalogListViewTest, self).setUp()
        self.catalog_user = UserFactory()
        self.url = reverse('api_admin:catalog-list', kwargs={'username': self.catalog_user.username})

    @httpretty.activate
    def test_get(self):
        catalog = CatalogFactory(viewers=[self.catalog_user.username])
        self.mock_catalog_endpoint({'results': [catalog.attributes]})
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(catalog.name, response.content.decode('utf-8'))

    @httpretty.activate
    def test_get_no_catalogs(self):
        """Verify that the view works when no catalogs are set up."""
        self.mock_catalog_endpoint({}, status_code=404)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    @httpretty.activate
    def test_post(self):
        catalog_data = {
            'name': 'test-catalog',
            'query': '*',
            'viewers': [self.catalog_user.username]
        }
        catalog_id = 123
        self.mock_catalog_endpoint(dict(catalog_data, id=catalog_id), method=httpretty.POST)
        response = self.client.post(self.url, catalog_data)
        self.assertEqual(httpretty.last_request().method, 'POST')
        self.mock_catalog_endpoint(CatalogFactory().attributes, catalog_id=catalog_id)
        self.assertRedirects(response, reverse('api_admin:catalog-edit', kwargs={'catalog_id': catalog_id}))

    @httpretty.activate
    def test_post_invalid(self):
        catalog = CatalogFactory(viewers=[self.catalog_user.username])
        self.mock_catalog_endpoint({'results': [catalog.attributes]})
        response = self.client.post(self.url, {
            'name': '',
            'query': '*',
            'viewers': [self.catalog_user.username]
        })
        self.assertEqual(response.status_code, 400)
        # Assert that no POST was made to the catalog API
        self.assertEqual(len([r for r in httpretty.httpretty.latest_requests if r.method == 'POST']), 0)


@skip_unless_lms
class CatalogEditViewTest(CatalogTest):
    """
    Test edits to the catalog endpoint.
    """
    def setUp(self):
        super(CatalogEditViewTest, self).setUp()
        self.catalog_user = UserFactory()
        self.catalog = CatalogFactory(viewers=[self.catalog_user.username])
        self.url = reverse('api_admin:catalog-edit', kwargs={'catalog_id': self.catalog.id})

    @httpretty.activate
    def test_get(self):
        self.mock_catalog_endpoint(self.catalog.attributes, catalog_id=self.catalog.id)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.catalog.name, response.content.decode('utf-8'))

    @httpretty.activate
    def test_delete(self):
        self.mock_catalog_endpoint(
            self.catalog.attributes,
            method=httpretty.DELETE,
            catalog_id=self.catalog.id
        )
        response = self.client.post(self.url, {'delete-catalog': 'on'})
        self.assertRedirects(response, reverse('api_admin:catalog-search'))
        self.assertEqual(httpretty.last_request().method, 'DELETE')
        self.assertEqual(
            httpretty.last_request().path,
            '/api/v1/catalogs/{}/'.format(self.catalog.id)
        )
        self.assertEqual(len(httpretty.httpretty.latest_requests), 1)

    @httpretty.activate
    def test_edit(self):
        self.mock_catalog_endpoint(self.catalog.attributes, method=httpretty.PATCH, catalog_id=self.catalog.id)
        new_attributes = dict(self.catalog.attributes, **{'delete-catalog': 'off', 'name': 'changed'})
        response = self.client.post(self.url, new_attributes)
        self.mock_catalog_endpoint(new_attributes, catalog_id=self.catalog.id)
        self.assertRedirects(response, reverse('api_admin:catalog-edit', kwargs={'catalog_id': self.catalog.id}))

    @httpretty.activate
    def test_edit_invalid(self):
        self.mock_catalog_endpoint(self.catalog.attributes, catalog_id=self.catalog.id)
        new_attributes = dict(self.catalog.attributes, **{'delete-catalog': 'off', 'name': ''})
        response = self.client.post(self.url, new_attributes)
        self.assertEqual(response.status_code, 400)
        # Assert that no PATCH was made to the Catalog API
        self.assertEqual(len([r for r in httpretty.httpretty.latest_requests if r.method == 'PATCH']), 0)


@skip_unless_lms
class CatalogPreviewViewTest(CatalogTest):
    """
    Test the catalog preview endpoint.
    """
    def setUp(self):
        super(CatalogPreviewViewTest, self).setUp()
        self.url = reverse('api_admin:catalog-preview')

    @httpretty.activate
    def test_get(self):
        data = {'count': 1, 'results': ['test data'], 'next': None, 'prev': None}
        httpretty.register_uri(
            httpretty.GET,
            '{root}/courses/'.format(root=settings.COURSE_CATALOG_API_URL.rstrip('/')),
            body=json.dumps(data),
            content_type='application/json'
        )
        response = self.client.get(self.url, {'q': '*'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), data)

    def test_get_without_query(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'count': 0, 'results': [], 'next': None, 'prev': None})
