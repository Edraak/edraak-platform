"""Integration tests for pipeline.py."""

import unittest

import datetime
import mock
import pytz
import ddt
from django import test
from django.contrib.auth import models
from django.core import mail
from social_django import models as social_models

from student.tests.factories import UserFactory
from third_party_auth import pipeline, provider
from third_party_auth.tests import testutil
from lms.djangoapps.verify_student.models import SSOVerification

# Get Django User model by reference from python-social-auth. Not a type
# constant, pylint.
User = social_models.DjangoStorage.user.user_model()  # pylint: disable=invalid-name


class TestCase(testutil.TestCase, test.TestCase):
    """Base test case."""

    def setUp(self):
        super(TestCase, self).setUp()
        self.enabled_provider = self.configure_google_provider(enabled=True)


@unittest.skipUnless(testutil.AUTH_FEATURE_ENABLED, testutil.AUTH_FEATURES_KEY + ' not enabled')
class GetAuthenticatedUserTestCase(TestCase):
    """Tests for get_authenticated_user."""

    def setUp(self):
        super(GetAuthenticatedUserTestCase, self).setUp()
        self.user = social_models.DjangoStorage.user.create_user(username='username', password='password')

    def get_by_username(self, username):
        """Gets a User by username."""
        return social_models.DjangoStorage.user.user_model().objects.get(username=username)

    def test_raises_does_not_exist_if_user_missing(self):
        with self.assertRaises(models.User.DoesNotExist):
            pipeline.get_authenticated_user(self.enabled_provider, 'new_' + self.user.username, 'user@example.com')

    def test_raises_does_not_exist_if_user_found_but_no_association(self):
        backend_name = 'backend'

        self.assertIsNotNone(self.get_by_username(self.user.username))
        self.assertFalse(any(provider.Registry.get_enabled_by_backend_name(backend_name)))

        with self.assertRaises(models.User.DoesNotExist):
            pipeline.get_authenticated_user(self.enabled_provider, self.user.username, 'user@example.com')

    def test_raises_does_not_exist_if_user_and_association_found_but_no_match(self):
        self.assertIsNotNone(self.get_by_username(self.user.username))
        social_models.DjangoStorage.user.create_social_auth(
            self.user, 'uid', 'other_' + self.enabled_provider.backend_name)

        with self.assertRaises(models.User.DoesNotExist):
            pipeline.get_authenticated_user(self.enabled_provider, self.user.username, 'uid')

    def test_returns_user_with_is_authenticated_and_backend_set_if_match(self):
        social_models.DjangoStorage.user.create_social_auth(self.user, 'uid', self.enabled_provider.backend_name)
        user = pipeline.get_authenticated_user(self.enabled_provider, self.user.username, 'uid')

        self.assertEqual(self.user, user)
        self.assertEqual(self.enabled_provider.get_authentication_backend(), user.backend)


@unittest.skipUnless(testutil.AUTH_FEATURE_ENABLED, testutil.AUTH_FEATURES_KEY + ' not enabled')
class GetProviderUserStatesTestCase(testutil.TestCase, test.TestCase):
    """Tests generation of ProviderUserStates."""

    def setUp(self):
        super(GetProviderUserStatesTestCase, self).setUp()
        self.user = social_models.DjangoStorage.user.create_user(username='username', password='password')

    def test_returns_empty_list_if_no_enabled_providers(self):
        self.assertFalse(provider.Registry.enabled())
        self.assertEquals([], pipeline.get_provider_user_states(self.user))

    def test_state_not_returned_for_disabled_provider(self):
        disabled_provider = self.configure_google_provider(enabled=False)
        enabled_provider = self.configure_facebook_provider(enabled=True)
        social_models.DjangoStorage.user.create_social_auth(self.user, 'uid', disabled_provider.backend_name)
        states = pipeline.get_provider_user_states(self.user)

        self.assertEqual(1, len(states))
        self.assertNotIn(disabled_provider.provider_id, (state.provider.provider_id for state in states))
        self.assertIn(enabled_provider.provider_id, (state.provider.provider_id for state in states))

    def test_states_for_enabled_providers_user_has_accounts_associated_with(self):
        # Enable two providers - Google and LinkedIn:
        google_provider = self.configure_google_provider(enabled=True)
        linkedin_provider = self.configure_linkedin_provider(enabled=True)
        user_social_auth_google = social_models.DjangoStorage.user.create_social_auth(
            self.user, 'uid', google_provider.backend_name)
        user_social_auth_linkedin = social_models.DjangoStorage.user.create_social_auth(
            self.user, 'uid', linkedin_provider.backend_name)
        states = pipeline.get_provider_user_states(self.user)

        self.assertEqual(2, len(states))

        google_state = [state for state in states if state.provider.provider_id == google_provider.provider_id][0]
        linkedin_state = [state for state in states if state.provider.provider_id == linkedin_provider.provider_id][0]

        self.assertTrue(google_state.has_account)
        self.assertEqual(google_provider.provider_id, google_state.provider.provider_id)
        # Also check the row ID. Note this 'id' changes whenever the configuration does:
        self.assertEqual(google_provider.id, google_state.provider.id)
        self.assertEqual(self.user, google_state.user)
        self.assertEqual(user_social_auth_google.id, google_state.association_id)

        self.assertTrue(linkedin_state.has_account)
        self.assertEqual(linkedin_provider.provider_id, linkedin_state.provider.provider_id)
        self.assertEqual(linkedin_provider.id, linkedin_state.provider.id)
        self.assertEqual(self.user, linkedin_state.user)
        self.assertEqual(user_social_auth_linkedin.id, linkedin_state.association_id)

    def test_states_for_enabled_providers_user_has_no_account_associated_with(self):
        # Enable two providers - Google and LinkedIn:
        google_provider = self.configure_google_provider(enabled=True)
        linkedin_provider = self.configure_linkedin_provider(enabled=True)
        self.assertEqual(len(provider.Registry.enabled()), 2)

        states = pipeline.get_provider_user_states(self.user)

        self.assertEqual([], [x for x in social_models.DjangoStorage.user.objects.all()])
        self.assertEqual(2, len(states))

        google_state = [state for state in states if state.provider.provider_id == google_provider.provider_id][0]
        linkedin_state = [state for state in states if state.provider.provider_id == linkedin_provider.provider_id][0]

        self.assertFalse(google_state.has_account)
        self.assertEqual(google_provider.provider_id, google_state.provider.provider_id)
        # Also check the row ID. Note this 'id' changes whenever the configuration does:
        self.assertEqual(google_provider.id, google_state.provider.id)
        self.assertEqual(self.user, google_state.user)

        self.assertFalse(linkedin_state.has_account)
        self.assertEqual(linkedin_provider.provider_id, linkedin_state.provider.provider_id)
        self.assertEqual(linkedin_provider.id, linkedin_state.provider.id)
        self.assertEqual(self.user, linkedin_state.user)


@unittest.skipUnless(testutil.AUTH_FEATURE_ENABLED, testutil.AUTH_FEATURES_KEY + ' not enabled')
class UrlFormationTestCase(TestCase):
    """Tests formation of URLs for pipeline hook points."""

    def test_complete_url_raises_value_error_if_provider_not_enabled(self):
        provider_name = 'oa2-not-enabled'

        self.assertIsNone(provider.Registry.get(provider_name))

        with self.assertRaises(ValueError):
            pipeline.get_complete_url(provider_name)

    def test_complete_url_returns_expected_format(self):
        complete_url = pipeline.get_complete_url(self.enabled_provider.backend_name)

        self.assertTrue(complete_url.startswith('/auth/complete'))
        self.assertIn(self.enabled_provider.backend_name, complete_url)

    def test_disconnect_url_raises_value_error_if_provider_not_enabled(self):
        provider_name = 'oa2-not-enabled'

        self.assertIsNone(provider.Registry.get(provider_name))

        with self.assertRaises(ValueError):
            pipeline.get_disconnect_url(provider_name, 1000)

    def test_disconnect_url_returns_expected_format(self):
        disconnect_url = pipeline.get_disconnect_url(self.enabled_provider.provider_id, 1000)
        disconnect_url = disconnect_url.rstrip('?')
        self.assertEqual(
            disconnect_url,
            '/auth/disconnect/{backend}/{association_id}/'.format(
                backend=self.enabled_provider.backend_name, association_id=1000)
        )

    def test_login_url_raises_value_error_if_provider_not_enabled(self):
        provider_id = 'oa2-not-enabled'

        self.assertIsNone(provider.Registry.get(provider_id))

        with self.assertRaises(ValueError):
            pipeline.get_login_url(provider_id, pipeline.AUTH_ENTRY_LOGIN)

    def test_login_url_returns_expected_format(self):
        login_url = pipeline.get_login_url(self.enabled_provider.provider_id, pipeline.AUTH_ENTRY_LOGIN)

        self.assertTrue(login_url.startswith('/auth/login'))
        self.assertIn(self.enabled_provider.backend_name, login_url)
        self.assertTrue(login_url.endswith(pipeline.AUTH_ENTRY_LOGIN))

    def test_for_value_error_if_provider_id_invalid(self):
        provider_id = 'invalid'  # Format is normally "{prefix}-{identifier}"

        with self.assertRaises(ValueError):
            provider.Registry.get(provider_id)

        with self.assertRaises(ValueError):
            pipeline.get_login_url(provider_id, pipeline.AUTH_ENTRY_LOGIN)

        with self.assertRaises(ValueError):
            pipeline.get_disconnect_url(provider_id, 1000)

        with self.assertRaises(ValueError):
            pipeline.get_complete_url(provider_id)


@unittest.skipUnless(testutil.AUTH_FEATURE_ENABLED, testutil.AUTH_FEATURES_KEY + ' not enabled')
class TestPipelineUtilityFunctions(TestCase, test.TestCase):
    """
    Test some of the isolated utility functions in the pipeline
    """
    def setUp(self):
        super(TestPipelineUtilityFunctions, self).setUp()
        self.user = social_models.DjangoStorage.user.create_user(username='username', password='password')
        self.social_auth = social_models.UserSocialAuth.objects.create(
            user=self.user,
            uid='fake uid',
            provider='fake provider'
        )

    def test_get_real_social_auth_from_dict(self):
        """
        Test that we can use a dictionary with a UID entry to retrieve a
        database-backed UserSocialAuth object.
        """
        request = mock.MagicMock()
        pipeline_partial = {
            'kwargs': {
                'social': {
                    'uid': 'fake uid'
                }
            }
        }

        with mock.patch('third_party_auth.pipeline.get') as get_pipeline:
            get_pipeline.return_value = pipeline_partial
            real_social = pipeline.get_real_social_auth_object(request)
            self.assertEqual(real_social, self.social_auth)

    def test_get_real_social_auth(self):
        """
        Test that trying to get a database-backed UserSocialAuth from an existing
        instance returns correctly.
        """
        request = mock.MagicMock()
        pipeline_partial = {
            'kwargs': {
                'social': self.social_auth
            }
        }

        with mock.patch('third_party_auth.pipeline.get') as get_pipeline:
            get_pipeline.return_value = pipeline_partial
            real_social = pipeline.get_real_social_auth_object(request)
            self.assertEqual(real_social, self.social_auth)

    def test_get_real_social_auth_no_pipeline(self):
        """
        Test that if there's no running pipeline, we return None when looking
        for a database-backed UserSocialAuth object.
        """
        request = mock.MagicMock(session={})
        real_social = pipeline.get_real_social_auth_object(request)
        self.assertEqual(real_social, None)

    def test_get_real_social_auth_no_social(self):
        """
        Test that if a UserSocialAuth object hasn't been attached to the pipeline as
        `social`, we return none
        """
        request = mock.MagicMock(
            session={
                'running_pipeline': {
                    'kwargs': {}
                }
            }
        )
        real_social = pipeline.get_real_social_auth_object(request)
        self.assertEqual(real_social, None)

    def test_quarantine(self):
        """
        Test that quarantining a session adds the correct flags, and that
        lifting the quarantine similarly removes those flags.
        """
        request = mock.MagicMock(
            session={}
        )
        pipeline.quarantine_session(request, locations=('my_totally_real_module', 'other_real_module',))
        self.assertEqual(
            request.session['third_party_auth_quarantined_modules'],
            ('my_totally_real_module', 'other_real_module',),
        )
        pipeline.lift_quarantine(request)
        self.assertNotIn('third_party_auth_quarantined_modules', request.session)


@unittest.skipUnless(testutil.AUTH_FEATURE_ENABLED, testutil.AUTH_FEATURES_KEY + ' not enabled')
@ddt.ddt
class EnsureUserInformationTestCase(testutil.TestCase, test.TestCase):
    """Tests ensuring that we have the necessary user information to proceed with the pipeline."""

    @ddt.data(
        (True, '/register'),
        (False, '/login')
    )
    @ddt.unpack
    def test_provider_settings_redirect_to_registration(self, send_to_registration_first, expected_redirect_url):
        """
        Test if user is not authenticated, that they get redirected to the appropriate page
        based on the provider's setting for send_to_registration_first.
        """

        provider = mock.MagicMock(
            send_to_registration_first=send_to_registration_first,
            skip_email_verification=False
        )

        with mock.patch('third_party_auth.pipeline.provider.Registry.get_from_pipeline') as get_from_pipeline:
            get_from_pipeline.return_value = provider
            with mock.patch('social_core.pipeline.partial.partial_prepare') as partial_prepare:
                partial_prepare.return_value = mock.MagicMock(token='')
                strategy = mock.MagicMock()
                response = pipeline.ensure_user_information(
                    strategy=strategy,
                    backend=None,
                    auth_entry=pipeline.AUTH_ENTRY_LOGIN,
                    pipeline_index=0
                )
                assert response.status_code == 302
                assert response.url == expected_redirect_url


@unittest.skipUnless(testutil.AUTH_FEATURE_ENABLED, testutil.AUTH_FEATURES_KEY + ' not enabled')
class UserDetailsForceSyncTestCase(testutil.TestCase, test.TestCase):
    """Tests to ensure learner profile data is properly synced if the provider requires it."""

    def setUp(self):
        super(UserDetailsForceSyncTestCase, self).setUp()
        self.user = UserFactory.create()
        self.old_email = self.user.email
        self.old_username = self.user.username
        self.old_fullname = self.user.profile.name
        self.details = {
            'email': 'new+{}'.format(self.user.email),
            'username': 'new_{}'.format(self.user.username),
            'fullname': 'Grown Up {}'.format(self.user.profile.name),
            'country': 'PK',
            'non_existing_field': 'value',
        }

        # Mocks
        self.strategy = mock.MagicMock()
        self.strategy.storage.user.changed.side_effect = lambda user: user.save()

        get_from_pipeline = mock.patch('third_party_auth.pipeline.provider.Registry.get_from_pipeline')
        self.get_from_pipeline = get_from_pipeline.start()
        self.get_from_pipeline.return_value = mock.MagicMock(sync_learner_profile_data=True)
        self.addCleanup(get_from_pipeline.stop)

    def test_user_details_force_sync(self):
        """
        The user details are synced properly and an email is sent when the email is changed.
        """
        # Begin the pipeline.
        pipeline.user_details_force_sync(
            auth_entry=pipeline.AUTH_ENTRY_LOGIN,
            strategy=self.strategy,
            details=self.details,
            user=self.user,
        )

        # User now has updated information in the DB.
        user = User.objects.get()
        assert user.email == 'new+{}'.format(self.old_email)
        assert user.profile.name == 'Grown Up {}'.format(self.old_fullname)
        assert user.profile.country == 'PK'

        # Now verify that username field is not updated
        assert user.username == self.old_username

        assert len(mail.outbox) == 1

    def test_user_details_force_sync_email_conflict(self):
        """
        The user details were attempted to be synced but the incoming email already exists for another account.
        """
        # Create a user with an email that conflicts with the incoming value.
        UserFactory.create(email='new+{}'.format(self.old_email))

        # Begin the pipeline.
        pipeline.user_details_force_sync(
            auth_entry=pipeline.AUTH_ENTRY_LOGIN,
            strategy=self.strategy,
            details=self.details,
            user=self.user,
        )

        # The email is not changed, but everything else is.
        user = User.objects.get(pk=self.user.pk)
        assert user.email == self.old_email
        assert user.profile.name == 'Grown Up {}'.format(self.old_fullname)
        assert user.profile.country == 'PK'

        # Now verify that username field is not updated
        assert user.username == self.old_username

        # No email should be sent for an email change.
        assert len(mail.outbox) == 0

    def test_user_details_force_sync_username_conflict(self):
        """
        The user details were attempted to be synced but the incoming username already exists for another account.

        An email should still be sent in this case.
        """
        # Create a user with an email that conflicts with the incoming value.
        UserFactory.create(username='new_{}'.format(self.old_username))

        # Begin the pipeline.
        pipeline.user_details_force_sync(
            auth_entry=pipeline.AUTH_ENTRY_LOGIN,
            strategy=self.strategy,
            details=self.details,
            user=self.user,
        )

        # The username is not changed, but everything else is.
        user = User.objects.get(pk=self.user.pk)
        assert user.email == 'new+{}'.format(self.old_email)
        assert user.username == self.old_username
        assert user.profile.name == 'Grown Up {}'.format(self.old_fullname)
        assert user.profile.country == 'PK'

        # An email should still be sent because the email changed.
        assert len(mail.outbox) == 1


@unittest.skipUnless(testutil.AUTH_FEATURE_ENABLED, testutil.AUTH_FEATURES_KEY + ' not enabled')
class SetIDVerificationStatusTestCase(testutil.TestCase, test.TestCase):
    """Tests to ensure SSO ID Verification for the user is set if the provider requires it."""

    def setUp(self):
        super(SetIDVerificationStatusTestCase, self).setUp()
        self.user = UserFactory.create()
        self.provider_class_name = 'third_party_auth.models.SAMLProviderConfig'
        self.provider_slug = 'default'
        self.details = {}

        # Mocks
        self.strategy = mock.MagicMock()
        self.strategy.storage.user.changed.side_effect = lambda user: user.save()

        get_from_pipeline = mock.patch('third_party_auth.pipeline.provider.Registry.get_from_pipeline')
        self.get_from_pipeline = get_from_pipeline.start()
        self.get_from_pipeline.return_value = mock.MagicMock(
            enable_sso_id_verification=True,
            full_class_name=self.provider_class_name,
            slug=self.provider_slug,
        )
        self.addCleanup(get_from_pipeline.stop)

    def test_set_id_verification_status_new_user(self):
        """
        The user details are synced properly and an email is sent when the email is changed.
        """
        # Begin the pipeline.
        pipeline.set_id_verification_status(
            auth_entry=pipeline.AUTH_ENTRY_LOGIN,
            strategy=self.strategy,
            details=self.details,
            user=self.user,
        )

        verification = SSOVerification.objects.get(user=self.user)

        assert verification.identity_provider_type == self.provider_class_name
        assert verification.identity_provider_slug == self.provider_slug
        assert verification.status == 'approved'
        assert verification.name == self.user.profile.name

    def test_set_id_verification_status_returning_user(self):
        """
        The user details are synced properly and an email is sent when the email is changed.
        """

        SSOVerification.objects.create(
            user=self.user,
            status="approved",
            name=self.user.profile.name,
            identity_provider_type=self.provider_class_name,
            identity_provider_slug=self.provider_slug,
        )

        # Begin the pipeline.
        pipeline.set_id_verification_status(
            auth_entry=pipeline.AUTH_ENTRY_LOGIN,
            strategy=self.strategy,
            details=self.details,
            user=self.user,
        )

        assert SSOVerification.objects.filter(user=self.user).count() == 1

    def test_set_id_verification_status_expired(self):
        """
        The user details are synced properly and an email is sent when the email is changed.
        """

        SSOVerification.objects.create(
            user=self.user,
            status="approved",
            name=self.user.profile.name,
            identity_provider_type=self.provider_class_name,
            identity_provider_slug=self.provider_slug,
        )

        with mock.patch('third_party_auth.pipeline.earliest_allowed_verification_date') as earliest_date:
            earliest_date.return_value = datetime.datetime.now(pytz.UTC) + datetime.timedelta(days=1)
            # Begin the pipeline.
            pipeline.set_id_verification_status(
                auth_entry=pipeline.AUTH_ENTRY_LOGIN,
                strategy=self.strategy,
                details=self.details,
                user=self.user,
            )

            assert SSOVerification.objects.filter(
                user=self.user,
                status="approved",
                name=self.user.profile.name,
                identity_provider_type=self.provider_class_name,
                identity_provider_slug=self.provider_slug,
            ).count() == 2
