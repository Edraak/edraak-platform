"""
Tests for Blocks Views
"""

import json
import unittest

import ddt
import httpretty
from django.conf import settings
from django.urls import reverse
from django.test import RequestFactory, TestCase
from mock import call, patch

from Cryptodome.PublicKey import RSA
from jwkest import jwk

from oauth2_provider import models as dot_models
from organizations.tests.factories import OrganizationFactory

from openedx.core.djangoapps.oauth_dispatch.toggles import ENFORCE_JWT_SCOPES
from provider import constants
from student.tests.factories import UserFactory
from third_party_auth.tests.utils import ThirdPartyOAuthTestMixin, ThirdPartyOAuthTestMixinGoogle
from . import mixins

# NOTE (CCB): We use this feature flag in a roundabout way to determine if the oauth_dispatch app is installed
# in the current service--LMS or Studio. Normally we would check if settings.ROOT_URLCONF == 'lms.urls'; however,
# simply importing the views will results in an error due to the requisite apps not being installed (in Studio). Thus,
# we are left with this hack, of checking the feature flag which will never be True for Studio.
#
# NOTE (BJM): As of Django 1.9 we also can't import models for apps which aren't in INSTALLED_APPS, so making all of
# these imports conditional except mixins, which doesn't currently import forbidden models, and is needed at test
# discovery time.
OAUTH_PROVIDER_ENABLED = settings.FEATURES.get('ENABLE_OAUTH2_PROVIDER')

if OAUTH_PROVIDER_ENABLED:
    from .constants import DUMMY_REDIRECT_URL
    from .. import adapters
    from .. import models
    from .. import views


class AccessTokenLoginMixin(object):
    """
    Shared helper class to assert proper access levels when using access_tokens
    """

    def setUp(self):
        """
        Initialize mixin
        """
        super(AccessTokenLoginMixin, self).setUp()
        self.login_with_access_token_url = reverse("login_with_access_token")

    def login_with_access_token(self, access_token=None):
        """
        Login with access token and return response.
        You can optionally send in an accss_token to override
        the object's attribute
        """

        return self.client.post(
            self.login_with_access_token_url,
            HTTP_AUTHORIZATION="Bearer {0}".format(access_token if access_token else self.access_token)
        )

    def _assert_access_token_is_valid(self, access_token=None):
        """
        Asserts that oauth assigned access_token is valid and usable
        """
        self.assertEqual(self.login_with_access_token(access_token=access_token).status_code, 204)

    def _assert_access_token_invalidated(self, access_token=None):
        """
        Asserts that oauth assigned access_token is not valid
        """
        self.assertEqual(self.login_with_access_token(access_token=access_token).status_code, 401)


@unittest.skipUnless(OAUTH_PROVIDER_ENABLED, 'OAuth2 not enabled')
class _DispatchingViewTestCase(TestCase):
    """
    Base class for tests that exercise DispatchingViews.

    Subclasses need to define self.url.
    """
    def setUp(self):
        super(_DispatchingViewTestCase, self).setUp()
        self.dop_adapter = adapters.DOPAdapter()
        self.dot_adapter = adapters.DOTAdapter()
        self.user = UserFactory()
        self.dot_app = self.dot_adapter.create_public_client(
            name='test dot application',
            user=self.user,
            redirect_uri=DUMMY_REDIRECT_URL,
            client_id='dot-app-client-id',
        )
        self.dop_app = self.dop_adapter.create_public_client(
            name='test dop client',
            user=self.user,
            redirect_uri=DUMMY_REDIRECT_URL,
            client_id='dop-app-client-id',
        )

        self.dot_app_access = models.ApplicationAccess.objects.create(
            application=self.dot_app,
            scopes=['grades:read'],
        )
        self.dot_app_org = models.ApplicationOrganization.objects.create(
            application=self.dot_app,
            organization=OrganizationFactory()
        )

        # Create a "restricted" DOT Application which means any AccessToken/JWT
        # generated for this application will be immediately expired
        self.restricted_dot_app = self.dot_adapter.create_public_client(
            name='test restricted dot application',
            user=self.user,
            redirect_uri=DUMMY_REDIRECT_URL,
            client_id='dot-restricted-app-client-id',
        )
        models.RestrictedApplication.objects.create(application=self.restricted_dot_app)

    def _post_request(self, user, client, token_type=None, scope=None):
        """
        Call the view with a POST request object with the appropriate format,
        returning the response object.
        """
        return self.client.post(self.url, self._post_body(user, client, token_type, scope))  # pylint: disable=no-member

    def _post_body(self, user, client, token_type=None, scope=None):
        """
        Return a dictionary to be used as the body of the POST request
        """
        raise NotImplementedError()


@ddt.ddt
class TestAccessTokenView(AccessTokenLoginMixin, mixins.AccessTokenMixin, _DispatchingViewTestCase):
    """
    Test class for AccessTokenView
    """

    def setUp(self):
        super(TestAccessTokenView, self).setUp()
        self.url = reverse('access_token')
        self.view_class = views.AccessTokenView

    def _post_body(self, user, client, token_type=None, scope=None):
        """
        Return a dictionary to be used as the body of the POST request
        """
        grant_type = getattr(client, 'authorization_grant_type', dot_models.Application.GRANT_PASSWORD)
        body = {
            'client_id': client.client_id,
            'grant_type': grant_type.replace('-', '_'),
        }

        if grant_type == dot_models.Application.GRANT_PASSWORD:
            body['username'] = user.username
            body['password'] = 'test'
        elif grant_type == dot_models.Application.GRANT_CLIENT_CREDENTIALS:
            body['client_secret'] = client.client_secret

        if token_type:
            body['token_type'] = token_type

        if scope:
            body['scope'] = scope

        return body

    def _generate_key_pair(self):
        """ Generates an asymmetric key pair and returns the JWK of its public keys and keypair. """
        rsa_key = RSA.generate(2048)
        rsa_jwk = jwk.RSAKey(kid="key_id", key=rsa_key)

        public_keys = jwk.KEYS()
        public_keys.append(rsa_jwk)
        serialized_public_keys_json = public_keys.dump_jwks()

        serialized_keypair = rsa_jwk.serialize(private=True)
        serialized_keypair_json = json.dumps(serialized_keypair)

        return serialized_public_keys_json, serialized_keypair_json

    @ddt.data('dop_app', 'dot_app')
    def test_access_token_fields(self, client_attr):
        client = getattr(self, client_attr)
        response = self._post_request(self.user, client)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('access_token', data)
        self.assertIn('expires_in', data)
        self.assertIn('scope', data)
        self.assertIn('token_type', data)

    @ddt.data(False, True)
    def test_restricted_non_jwt_access_token_fields(self, enforce_jwt_scopes_enabled):
        with ENFORCE_JWT_SCOPES.override(enforce_jwt_scopes_enabled):
            response = self._post_request(self.user, self.restricted_dot_app)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertIn('access_token', data)
            self.assertIn('expires_in', data)
            self.assertIn('scope', data)
            self.assertIn('token_type', data)

            # Verify token expiration.
            self.assertEqual(data['expires_in'] < 0, True)
            access_token = dot_models.AccessToken.objects.get(token=data['access_token'])
            self.assertEqual(
                models.RestrictedApplication.verify_access_token_as_expired(access_token),
                True
            )

    @ddt.data('dop_app', 'dot_app')
    def test_jwt_access_token(self, client_attr):
        client = getattr(self, client_attr)
        response = self._post_request(self.user, client, token_type='jwt')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('expires_in', data)
        self.assertEqual(data['token_type'], 'JWT')
        self.assert_valid_jwt_access_token(
            data['access_token'],
            self.user,
            data['scope'].split(' '),
            should_be_restricted=False,
        )

    @ddt.data(
        ('jwt', 'jwt'),
        (None, 'no_token_type_supplied'),
    )
    @ddt.unpack
    @patch('edx_django_utils.monitoring.set_custom_metric')
    def test_access_token_metrics(self, token_type, expected_token_type, mock_set_custom_metric):
        response = self._post_request(self.user, self.dot_app, token_type=token_type)
        self.assertEqual(response.status_code, 200)
        expected_calls = [
            call('oauth_token_type', expected_token_type),
            call('oauth_grant_type', 'password'),
        ]
        mock_set_custom_metric.assert_has_calls(expected_calls, any_order=True)

    @patch('edx_django_utils.monitoring.set_custom_metric')
    def test_access_token_metrics_for_bad_request(self, mock_set_custom_metric):
        grant_type = dot_models.Application.GRANT_PASSWORD
        invalid_body = {
            'grant_type': grant_type.replace('-', '_'),
        }
        bad_response = self.client.post(self.url, invalid_body)
        self.assertEqual(bad_response.status_code, 400)
        expected_calls = [
            call('oauth_token_type', 'no_token_type_supplied'),
            call('oauth_grant_type', 'password'),
        ]
        mock_set_custom_metric.assert_has_calls(expected_calls, any_order=True)

    @ddt.data(
        (False, True),
        (True, False),
    )
    @ddt.unpack
    def test_restricted_jwt_access_token(self, enforce_jwt_scopes_enabled, expiration_expected):
        """
        Verify that when requesting a JWT token from a restricted Application
        within the DOT subsystem, that our claims is marked as already expired
        (i.e. expiry set to Jan 1, 1970)
        """
        with ENFORCE_JWT_SCOPES.override(enforce_jwt_scopes_enabled):
            response = self._post_request(self.user, self.restricted_dot_app, token_type='jwt')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)

            self.assertIn('expires_in', data)
            self.assertEqual(data['expires_in'] < 0, expiration_expected)
            self.assertEqual(data['token_type'], 'JWT')
            self.assert_valid_jwt_access_token(
                data['access_token'],
                self.user,
                data['scope'].split(' '),
                should_be_expired=expiration_expected,
                should_be_asymmetric_key=enforce_jwt_scopes_enabled,
                should_be_restricted=True,
            )

    def test_restricted_access_token(self):
        """
        Verify that an access_token generated for a RestrictedApplication fails when
        submitted to an API endpoint
        """

        response = self._post_request(self.user, self.restricted_dot_app)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        self.assertIn('expires_in', data)
        self.assertIn('access_token', data)

        # the payload should indicate that the token is expired
        self.assertLess(data['expires_in'], 0)

        # try submitting this expired access_token to an API,
        # and assert that it fails
        self._assert_access_token_invalidated(data['access_token'])

    def test_dot_access_token_provides_refresh_token(self):
        response = self._post_request(self.user, self.dot_app)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('refresh_token', data)

    def test_dop_public_client_access_token(self):
        response = self._post_request(self.user, self.dop_app)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertNotIn('refresh_token', data)

    @ddt.data(dot_models.Application.GRANT_CLIENT_CREDENTIALS, dot_models.Application.GRANT_PASSWORD)
    def test_jwt_access_token_scopes_and_filters(self, grant_type):
        """
        Verify the JWT contains the expected scopes and filters.
        """
        dot_app = self.dot_adapter.create_public_client(
            name='test dot application',
            user=self.user,
            redirect_uri=DUMMY_REDIRECT_URL,
            client_id='dot-app-client-id-{grant_type}'.format(grant_type=grant_type),
            grant_type=grant_type,
        )
        dot_app_access = models.ApplicationAccess.objects.create(
            application=dot_app,
            scopes=['grades:read'],
        )
        models.ApplicationOrganization.objects.create(
            application=dot_app,
            organization=OrganizationFactory()
        )
        scopes = dot_app_access.scopes
        filters = self.dot_adapter.get_authorization_filters(dot_app)
        response = self._post_request(self.user, dot_app, token_type='jwt', scope=scopes)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assert_valid_jwt_access_token(
            data['access_token'],
            self.user,
            scopes,
            filters=filters,
        )


@ddt.ddt
@httpretty.activate
class TestAccessTokenExchangeView(ThirdPartyOAuthTestMixinGoogle, ThirdPartyOAuthTestMixin, _DispatchingViewTestCase):
    """
    Test class for AccessTokenExchangeView
    """

    def setUp(self):
        self.url = reverse('exchange_access_token', kwargs={'backend': 'google-oauth2'})
        self.view_class = views.AccessTokenExchangeView
        super(TestAccessTokenExchangeView, self).setUp()

    def _post_body(self, user, client, token_type=None, scope=None):
        return {
            'client_id': client.client_id,
            'access_token': self.access_token,
        }

    @ddt.data('dop_app', 'dot_app')
    def test_access_token_exchange_calls_dispatched_view(self, client_attr):
        client = getattr(self, client_attr)
        self.oauth_client = client
        self._setup_provider_response(success=True)
        response = self._post_request(self.user, client)
        self.assertEqual(response.status_code, 200)


# pylint: disable=abstract-method
@ddt.ddt
class TestAuthorizationView(_DispatchingViewTestCase):
    """
    Test class for AuthorizationView
    """

    def setUp(self):
        super(TestAuthorizationView, self).setUp()
        self.dop_adapter = adapters.DOPAdapter()
        self.user = UserFactory()
        self.dot_app = self.dot_adapter.create_confidential_client(
            name='test dot application',
            user=self.user,
            redirect_uri=DUMMY_REDIRECT_URL,
            client_id='confidential-dot-app-client-id',
        )
        models.ApplicationAccess.objects.create(
            application=self.dot_app,
            scopes=['grades:read'],
        )
        self.dot_app_org = models.ApplicationOrganization.objects.create(
            application=self.dot_app,
            organization=OrganizationFactory()
        )
        self.dop_app = self.dop_adapter.create_confidential_client(
            name='test dop client',
            user=self.user,
            redirect_uri=DUMMY_REDIRECT_URL,
            client_id='confidential-dop-app-client-id',
        )

    @ddt.data(
        ('dop', 'authorize'),
        ('dot', 'allow')
    )
    @ddt.unpack
    def test_post_authorization_view(self, client_type, allow_field):
        oauth_application = getattr(self, '{}_app'.format(client_type))
        self.client.login(username=self.user.username, password='test')
        response = self.client.post(
            '/oauth2/authorize/',
            {
                'client_id': oauth_application.client_id,
                'response_type': 'code',
                'state': 'random_state_string',
                'redirect_uri': DUMMY_REDIRECT_URL,
                'scope': 'profile email',
                allow_field: True,
            },
            follow=True,
        )

        check_response = getattr(self, '_check_{}_response'.format(client_type))
        check_response(response)

    def test_check_dot_authorization_page_get(self):
        """
        Make sure we get the overridden Authorization page - not
        the default django-oauth-toolkit when we perform a page load
        """
        self.client.login(username=self.user.username, password='test')
        response = self.client.get(
            '/oauth2/authorize/',
            {
                'client_id': self.dot_app.client_id,
                'response_type': 'code',
                'state': 'random_state_string',
                'redirect_uri': DUMMY_REDIRECT_URL,
                'scope': 'profile grades:read'
            },
            follow=True,
        )

        # are the requested scopes on the page? We only requested 'profile', lets make
        # sure the page only lists that one
        self.assertContains(response, settings.OAUTH2_PROVIDER['SCOPES']['profile'])
        self.assertContains(response, settings.OAUTH2_PROVIDER['SCOPES']['grades:read'])
        self.assertNotContains(response, settings.OAUTH2_PROVIDER['SCOPES']['read'])
        self.assertNotContains(response, settings.OAUTH2_PROVIDER['SCOPES']['write'])
        self.assertNotContains(response, settings.OAUTH2_PROVIDER['SCOPES']['email'])

        # is the application name specified?
        self.assertContains(
            response,
            "Authorize {name}".format(name=self.dot_app.name)
        )

        # are the cancel and allow buttons on the page?
        self.assertContains(
            response,
            '<button type="submit" class="btn btn-authorization-cancel" name="cancel"/>Cancel</button>'
        )
        self.assertContains(
            response,
            '<button type="submit" class="btn btn-authorization-allow" name="allow" value="Authorize"/>Allow</button>'
        )

        # Are the content provider organizations listed on the page?
        self.assertContains(
            response,
            '<li>{org}</li>'.format(org=self.dot_app_org.organization.name)
        )

    def _check_dot_response(self, response):
        """
        Check that django-oauth-toolkit gives an appropriate authorization response.
        """
        # django-oauth-toolkit tries to redirect to the user's redirect URL
        self.assertEqual(response.status_code, 404)  # We used a non-existent redirect url.
        expected_redirect_prefix = u'{}?'.format(DUMMY_REDIRECT_URL)
        self._assert_startswith(self._redirect_destination(response), expected_redirect_prefix)

    def _check_dop_response(self, response):
        """
        Check that django-oauth2-provider gives an appropriate authorization response.
        """
        # django-oauth-provider redirects to a confirmation page
        self.assertRedirects(response, u'http://testserver/oauth2/authorize/confirm', target_status_code=200)

        context = response.context_data
        form = context['form']
        self.assertIsNone(form['authorize'].value())

        oauth_data = context['oauth_data']
        self.assertEqual(oauth_data['redirect_uri'], DUMMY_REDIRECT_URL)
        self.assertEqual(oauth_data['state'], 'random_state_string')
        # TODO: figure out why it chooses this scope.
        self.assertEqual(oauth_data['scope'], constants.READ_WRITE)

    def _assert_startswith(self, string, prefix):
        """
        Assert that the string starts with the specified prefix.
        """
        self.assertTrue(string.startswith(prefix), u'{} does not start with {}'.format(string, prefix))

    @staticmethod
    def _redirect_destination(response):
        """
        Return the final destination of the redirect chain in the response object
        """
        return response.redirect_chain[-1][0]


@unittest.skipUnless(OAUTH_PROVIDER_ENABLED, 'OAuth2 not enabled')
class TestViewDispatch(TestCase):
    """
    Test that the DispatchingView dispatches the right way.
    """

    def setUp(self):
        super(TestViewDispatch, self).setUp()
        self.dop_adapter = adapters.DOPAdapter()
        self.dot_adapter = adapters.DOTAdapter()
        self.user = UserFactory()
        self.view = views._DispatchingView()  # pylint: disable=protected-access
        self.dop_adapter.create_public_client(
            name='',
            user=self.user,
            client_id='dop-id',
            redirect_uri=DUMMY_REDIRECT_URL
        )
        self.dot_adapter.create_public_client(
            name='',
            user=self.user,
            client_id='dot-id',
            redirect_uri=DUMMY_REDIRECT_URL
        )

    def assert_is_view(self, view_candidate):
        """
        Assert that a given object is a view.  That is, it is callable, and
        takes a request argument.  Note: while technically, the request argument
        could take any name, this assertion requires the argument to be named
        `request`.  This is good practice.  You should do it anyway.
        """
        _msg_base = u'{view} is not a view: {reason}'
        msg_not_callable = _msg_base.format(view=view_candidate, reason=u'it is not callable')
        msg_no_request = _msg_base.format(view=view_candidate, reason=u'it has no request argument')
        self.assertTrue(hasattr(view_candidate, '__call__'), msg_not_callable)
        args = view_candidate.func_code.co_varnames
        self.assertTrue(args, msg_no_request)
        self.assertEqual(args[0], 'request')

    def _post_request(self, client_id):
        """
        Return a request with the specified client_id in the body
        """
        return RequestFactory().post('/', {'client_id': client_id})

    def _get_request(self, client_id):
        """
        Return a request with the specified client_id in the get parameters
        """
        return RequestFactory().get('/?client_id={}'.format(client_id))

    def _verify_oauth_metrics_calls(self, mock_set_custom_metric, expected_oauth_adapter):
        """
        Args:
            mock_set_custom_metric: MagicMock of set_custom_metric
            expected_oauth_adapter: Either 'dot' or 'dop'
        """
        expected_calls = [
            call('oauth_client_id', '{}-id'.format(expected_oauth_adapter)),
            call('oauth_adapter', expected_oauth_adapter),
        ]
        mock_set_custom_metric.assert_has_calls(expected_calls, any_order=True)

    @patch('edx_django_utils.monitoring.set_custom_metric')
    def test_dispatching_post_to_dot(self, mock_set_custom_metric):
        request = self._post_request('dot-id')
        self.assertEqual(self.view.select_backend(request), self.dot_adapter.backend)
        self._verify_oauth_metrics_calls(mock_set_custom_metric, 'dot')

    @patch('edx_django_utils.monitoring.set_custom_metric')
    def test_dispatching_post_to_dop(self, mock_set_custom_metric):
        request = self._post_request('dop-id')
        self.assertEqual(self.view.select_backend(request), self.dop_adapter.backend)
        self._verify_oauth_metrics_calls(mock_set_custom_metric, 'dop')

    def test_dispatching_get_to_dot(self):
        request = self._get_request('dot-id')
        self.assertEqual(self.view.select_backend(request), self.dot_adapter.backend)

    def test_dispatching_get_to_dop(self):
        request = self._get_request('dop-id')
        self.assertEqual(self.view.select_backend(request), self.dop_adapter.backend)

    def test_dispatching_with_no_client(self):
        request = self._post_request(None)
        self.assertEqual(self.view.select_backend(request), self.dop_adapter.backend)

    def test_dispatching_with_invalid_client(self):
        request = self._post_request('abcesdfljh')
        self.assertEqual(self.view.select_backend(request), self.dop_adapter.backend)

    def test_get_view_for_dot(self):
        view_object = views.AccessTokenView()
        self.assert_is_view(view_object.get_view_for_backend(self.dot_adapter.backend))

    def test_get_view_for_dop(self):
        view_object = views.AccessTokenView()
        self.assert_is_view(view_object.get_view_for_backend(self.dop_adapter.backend))

    def test_get_view_for_no_backend(self):
        view_object = views.AccessTokenView()
        self.assertRaises(KeyError, view_object.get_view_for_backend, None)


class TestRevokeTokenView(AccessTokenLoginMixin, _DispatchingViewTestCase):  # pylint: disable=abstract-method
    """
    Test class for RevokeTokenView
    """

    def setUp(self):
        self.revoke_token_url = reverse('revoke_token')
        self.access_token_url = reverse('access_token')

        super(TestRevokeTokenView, self).setUp()
        response = self.client.post(self.access_token_url, self.access_token_post_body_with_password())
        access_token_data = json.loads(response.content)
        self.access_token = access_token_data['access_token']
        self.refresh_token = access_token_data['refresh_token']

    def access_token_post_body_with_password(self):
        """
        Returns a dictionary to be used as the body of the access_token
        POST request with 'password' grant
        """
        return {
            'client_id': self.dot_app.client_id,
            'grant_type': 'password',
            'username': self.user.username,
            'password': 'test',
        }

    def access_token_post_body_with_refresh_token(self, refresh_token):
        """
        Returns a dictionary to be used as the body of the access_token
        POST request with 'refresh_token' grant
        """
        return {
            'client_id': self.dot_app.client_id,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }

    def revoke_token_post_body(self, token):
        """
        Returns a dictionary to be used as the body of the revoke_token POST request
        """
        return {
            'client_id': self.dot_app.client_id,
            'token': token,
        }

    def assert_refresh_token_status_code(self, refresh_token, expected_status_code):
        """
        Asserts the status code using oauth assigned refresh_token
        """
        response = self.client.post(
            self.access_token_url,
            self.access_token_post_body_with_refresh_token(refresh_token)
        )
        self.assertEqual(response.status_code, expected_status_code)

    def revoke_token(self, token):
        """
        Revokes the passed access or refresh token
        """
        response = self.client.post(self.revoke_token_url, self.revoke_token_post_body(token))
        self.assertEqual(response.status_code, 200)

    def test_revoke_refresh_token_dot(self):
        """
        Tests invalidation/revoke of refresh token for django-oauth-toolkit
        """
        self.assert_refresh_token_status_code(self.refresh_token, expected_status_code=200)

        self.revoke_token(self.refresh_token)

        self.assert_refresh_token_status_code(self.refresh_token, expected_status_code=401)

    def test_revoke_access_token_dot(self):
        """
        Tests invalidation/revoke of user access token for django-oauth-toolkit
        """
        self._assert_access_token_is_valid(self.access_token)

        self.revoke_token(self.access_token)

        self._assert_access_token_invalidated(self.access_token)
