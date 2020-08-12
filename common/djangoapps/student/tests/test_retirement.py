"""
Test user retirement methods
"""
import json

import ddt
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.test import TestCase
import pytest

from student.models import (
    _get_all_retired_emails_by_email,
    _get_all_retired_usernames_by_username,
    get_potentially_retired_user_by_username,
    get_potentially_retired_user_by_username_and_hash,
    get_retired_email_by_email,
    get_retired_username_by_username,
    is_username_retired,
    is_email_retired
)
from student.tests.factories import UserFactory


# Tell pytest it's ok to user the Django db
pytestmark = pytest.mark.django_db

# Make sure our settings are sane
assert settings.RETIRED_USERNAME_PREFIX
assert settings.RETIRED_EMAIL_PREFIX
assert settings.RETIRED_EMAIL_DOMAIN
assert "{}" in settings.RETIRED_USERNAME_FMT
assert "{}@" in settings.RETIRED_EMAIL_FMT


@pytest.fixture
def retirement_user():
    return UserFactory.create(username='test_user')


@pytest.fixture
def retirement_status(retirement_user):  # pylint: disable=redefined-outer-name
    """
    Returns a UserRetirementStatus test fixture object.
    """
    RetirementState = apps.get_model('user_api', 'RetirementState')
    UserRetirementStatus = apps.get_model('user_api', 'UserRetirementStatus')
    RetirementState.objects.create(
        state_name='RETIRING_LMS',
        state_execution_order=1,
        required=False,
        is_dead_end_state=False
    )
    status = UserRetirementStatus.create_retirement(retirement_user)
    status.save()
    return status


@pytest.fixture
def two_users_same_username_different_case(retirement_status):
    user1 = UserFactory.create(username='TestUser')
    user2 = UserFactory.create(username='testuser')
    UserRetirementStatus = apps.get_model('user_api', 'UserRetirementStatus')
    status = UserRetirementStatus.create_retirement(user1)
    user1.username = status.retired_username
    user1.save()
    return status, user1, user2


def check_username_against_fmt(hashed_username):
    """
    Checks that the given username is formatted correctly using our settings.
    """
    assert len(hashed_username) > len(settings.RETIRED_USERNAME_FMT)
    assert hashed_username.startswith(settings.RETIRED_USERNAME_PREFIX)


def check_email_against_fmt(hashed_email):
    """
    Checks that the given email is formatted correctly using our settings.
    """
    assert len(hashed_email) > len(settings.RETIRED_EMAIL_FMT)
    assert hashed_email.startswith(settings.RETIRED_EMAIL_PREFIX)
    assert hashed_email.endswith(settings.RETIRED_EMAIL_DOMAIN)


def test_get_retired_username(retirement_user):
    """
    Basic testing of getting retired usernames. The hasher is opaque
    to us, we just care that it's succeeding and using our format.
    """
    hashed_username = get_retired_username_by_username(retirement_user.username)
    check_username_against_fmt(hashed_username)


def test_get_retired_username_status_exists(retirement_user, retirement_status):  # pylint: disable=redefined-outer-name
    """
    Checks that a retired username is gotten from a UserRetirementStatus
    object when one already exists for a user.
    """
    hashed_username = get_retired_username_by_username(retirement_user.username)
    check_username_against_fmt(hashed_username)
    assert retirement_status.retired_username == hashed_username


def test_get_all_retired_usernames_by_username(retirement_user):
    """
    Check that all salts are used for this method and return expected
    formats.
    """
    hashed_usernames = list(_get_all_retired_usernames_by_username(retirement_user.username))
    assert len(hashed_usernames) == len(settings.RETIRED_USER_SALTS)

    for hashed_username in hashed_usernames:
        check_username_against_fmt(hashed_username)

    # Make sure hashes are unique
    assert len(hashed_usernames) == len(set(hashed_usernames))


def test_is_username_retired_is_retired(retirement_user):
    """
    Check functionality of is_username_retired when username is retired
    """
    original_username = retirement_user.username
    retired_username = get_retired_username_by_username(retirement_user.username)

    # Fake username retirement.
    retirement_user.username = retired_username
    retirement_user.save()

    assert is_username_retired(original_username)


def test_is_username_retired_not_retired(retirement_user):
    """
    Check functionality of is_username_retired when username is not retired
    """
    assert not is_username_retired(retirement_user.username)


def test_is_email_retired_is_retired(retirement_user):
    """
    Check functionality of is_email_retired when email is retired
    """
    original_email = retirement_user.email
    retired_email = get_retired_email_by_email(retirement_user.email)

    # Fake email retirement.
    retirement_user.email = retired_email
    retirement_user.save()

    assert is_email_retired(original_email)


def test_is_email_retired_not_retired(retirement_user):
    """
    Check functionality of is_email_retired when email is not retired
    """
    assert not is_email_retired(retirement_user.email)


def test_get_retired_email(retirement_user):
    """
    Basic testing of retired emails.
    """
    hashed_email = get_retired_email_by_email(retirement_user.email)
    check_email_against_fmt(hashed_email)


def test_get_retired_email_status_exists(retirement_user, retirement_status):  # pylint: disable=redefined-outer-name
    """
    Checks that a retired email is gotten from a UserRetirementStatus
    object when one already exists for a user.
    """
    hashed_email = get_retired_email_by_email(retirement_user.email)
    check_email_against_fmt(hashed_email)
    assert retirement_status.retired_email == hashed_email


def test_get_all_retired_email_by_email(retirement_user):
    """
    Check that all salts are used for this method and return expected
    formats.
    """
    hashed_emails = list(_get_all_retired_emails_by_email(retirement_user.email))
    assert len(hashed_emails) == len(settings.RETIRED_USER_SALTS)

    for hashed_email in hashed_emails:
        check_email_against_fmt(hashed_email)

    # Make sure hashes are unique
    assert len(hashed_emails) == len(set(hashed_emails))


def test_get_correct_user_varying_by_case_only(two_users_same_username_different_case):
    """
    Check that two users - one retired, one active - with the same username except for case can be found.
    """
    retired_status, retired_user, active_user = two_users_same_username_different_case
    first_user = get_potentially_retired_user_by_username(retired_status.original_username)
    second_user = get_potentially_retired_user_by_username(active_user.username)
    assert first_user.username != second_user.username
    assert second_user.username == active_user.username


def test_get_potentially_retired_user_username_match(retirement_user):
    """
    Check that we can pass in an un-retired username and get the
    user-to-be-retired back.
    """
    hashed_username = get_retired_username_by_username(retirement_user.username)
    assert get_potentially_retired_user_by_username_and_hash(retirement_user.username, hashed_username) == retirement_user


def test_get_potentially_retired_user_hashed_match(retirement_user):
    """
    Check that we can pass in a hashed username and get the
    user-to-be-retired back.
    """
    orig_username = retirement_user.username
    hashed_username = get_retired_username_by_username(orig_username)

    # Fake username retirement.
    retirement_user.username = hashed_username
    retirement_user.save()

    # Check to find the user by original username should fail,
    # 2nd check by hashed username should succeed.
    assert get_potentially_retired_user_by_username_and_hash(orig_username, hashed_username) == retirement_user


def test_get_potentially_retired_user_does_not_exist():
    """
    Check that the call to get a user with a non-existent
    username and hashed username bubbles up User.DoesNotExist
    """
    fake_username = "fake username"
    hashed_username = get_retired_username_by_username(fake_username)

    with pytest.raises(User.DoesNotExist):
        get_potentially_retired_user_by_username_and_hash(fake_username, hashed_username)


def test_get_potentially_retired_user_bad_hash():
    """
    Check that the call will raise an exeption if the given hash
    of the username doesn't match any salted hashes the system
    knows about.
    """
    fake_username = "fake username"

    with pytest.raises(Exception):
        get_potentially_retired_user_by_username_and_hash(fake_username, "bad hash")


@ddt.ddt
class TestRegisterRetiredUsername(TestCase):
    """
    Tests to ensure that retired usernames can no longer be used in registering new accounts.
    """
    # The returned message here varies depending on whether a ValidationError -or-
    # an AccountValidationError occurs.
    INVALID_ACCT_ERR_MSG = ('An account with the Public Username', 'already exists.')
    INVALID_ERR_MSG = ('It looks like', 'belongs to an existing account. Try again with a different username.')

    def setUp(self):
        super(TestRegisterRetiredUsername, self).setUp()
        self.url = reverse('user_api_registration')
        self.url_params = {
            'username': 'username',
            'email': 'foo_bar' + '@bar.com',
            'name': 'foo bar',
            'password': '123',
            'terms_of_service': 'true',
            'honor_code': 'true',
        }

    def _validate_exiting_username_response(self, orig_username, response, start_msg=INVALID_ACCT_ERR_MSG[0], end_msg=INVALID_ACCT_ERR_MSG[1]):
        """
        Validates a response stating that a username already exists -or- is invalid.
        """
        assert response.status_code == 409
        obj = json.loads(response.content)

        username_msg = obj['username'][0]['user_message']
        assert username_msg.startswith(start_msg)
        assert username_msg.endswith(end_msg)
        assert orig_username in username_msg

    def test_retired_username(self):
        """
        Ensure that a retired username cannot be registered again.
        """
        user = UserFactory()
        orig_username = user.username

        # Fake retirement of the username.
        user.username = get_retired_username_by_username(orig_username)
        user.save()

        # Attempt to create another account with the same username that's been retired.
        self.url_params['username'] = orig_username
        response = self.client.post(self.url, self.url_params)
        self._validate_exiting_username_response(orig_username, response, self.INVALID_ERR_MSG[0], self.INVALID_ERR_MSG[1])

    def test_username_close_to_retired_format_active(self):
        """
        Ensure that a username similar to the format of a retired username cannot be created.
        """
        # Attempt to create an account with a username similar to the format of a retired username
        # which matches the RETIRED_USERNAME_PREFIX setting.
        self.url_params['username'] = settings.RETIRED_USERNAME_PREFIX
        response = self.client.post(self.url, self.url_params)
        self._validate_exiting_username_response(settings.RETIRED_USERNAME_PREFIX, response)
