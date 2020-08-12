# -*- coding: utf-8 -*-
"""
Test cases to cover account retirement views
"""
from __future__ import print_function

import datetime
import importlib
import json
import unittest

import ddt
import pytz
import mock
from consent.models import DataSharingConsent
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core import mail
from django.core.cache import cache
from django.core.urlresolvers import reverse, resolve
from django.test import TestCase
from enterprise.models import (
    EnterpriseCustomer,
    EnterpriseCustomerUser,
    EnterpriseCourseEnrollment,
    PendingEnterpriseCustomerUser,
)
from integrated_channels.sap_success_factors.models import (
    SapSuccessFactorsLearnerDataTransmissionAudit
)
from opaque_keys.edx.keys import CourseKey
import pytz
from rest_framework import status, permissions
from six import iteritems, text_type
from social_django.models import UserSocialAuth
from wiki.models import ArticleRevision, Article
from wiki.models.pluginbase import RevisionPluginRevision, RevisionPlugin
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from entitlements.models import CourseEntitlementSupportDetail
from entitlements.tests.factories import CourseEntitlementFactory
from openedx.core.djangoapps.api_admin.models import ApiAccessRequest
from openedx.core.djangoapps.credit.models import (
    CreditRequirementStatus, CreditRequest, CreditCourse, CreditProvider, CreditRequirement
)
from openedx.core.djangoapps.course_groups.models import CourseUserGroup, UnregisteredLearnerCohortAssignments
from openedx.core.djangoapps.oauth_dispatch.jwt import create_jwt_for_user
from openedx.core.djangoapps.site_configuration.tests.factories import SiteFactory
from openedx.core.djangoapps.user_api.models import (
    RetirementState,
    UserRetirementStatus,
    UserRetirementPartnerReportingStatus,
    UserOrgTag
)
from openedx.core.djangoapps.user_api.accounts.views import AccountRetirementPartnerReportView
from student.models import (
    CourseEnrollment,
    CourseEnrollmentAllowed,
    ManualEnrollmentAudit,
    PendingEmailChange,
    PendingNameChange,
    Registration,
    SocialLink,
    UserProfile,
    get_retired_username_by_username,
    get_retired_email_by_email,
)
from student.tests.factories import (
    ContentTypeFactory,
    CourseEnrollmentAllowedFactory,
    PendingEmailChangeFactory,
    PermissionFactory,
    AdminFactory,
    SuperuserFactory,
    UserFactory
)

from ..permissions import CanRetireUser
from ..views import AccountRetirementView, USER_PROFILE_PII
from ...tests.factories import UserOrgTagFactory
from .retirement_helpers import (  # pylint: disable=unused-import
    RetirementTestCase,
    RetirementTestUserMixin,
    fake_completed_retirement,
    create_retirement_status,
    setup_retirement_states
)


def build_jwt_headers(user):
    """
    Helper function for creating headers for the JWT authentication.
    """
    token = create_jwt_for_user(user)
    headers = {
        'HTTP_AUTHORIZATION': 'JWT ' + token
    }
    return headers


def get_view_class_from_url(url):
    """
    Get the class view that will be resolved from a URL
    """
    view_func = resolve(url).func
    module = importlib.import_module(view_func.__module__)
    return getattr(module, view_func.__name__)


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestAccountDeactivation(TestCase):
    """
    Tests the account deactivation endpoint.
    """

    def setUp(self):
        super(TestAccountDeactivation, self).setUp()
        self.test_user = UserFactory()
        self.url = reverse('accounts_deactivation', kwargs={'username': self.test_user.username})

    def assert_activation_status(self, headers, expected_status=status.HTTP_200_OK, expected_activation_status=False):
        """
        Helper function for making a request to the deactivation endpoint, and asserting the status.

        Args:
            expected_status(int): Expected request's response status.
            expected_activation_status(bool): Expected user has_usable_password attribute value.
        """
        self.assertTrue(self.test_user.has_usable_password())
        response = self.client.post(self.url, **headers)
        self.assertEqual(response.status_code, expected_status)
        self.test_user.refresh_from_db()
        self.assertEqual(self.test_user.has_usable_password(), expected_activation_status)

    def test_superuser_deactivates_user(self):
        """
        Verify a user is deactivated when a superuser posts to the deactivation endpoint.
        """
        superuser = SuperuserFactory()
        headers = build_jwt_headers(superuser)
        self.assert_activation_status(headers)

    def test_user_with_permission_deactivates_user(self):
        """
        Verify a user is deactivated when a user with permission posts to the deactivation endpoint.
        """
        user = UserFactory()
        permission = PermissionFactory(
            codename='can_deactivate_users',
            content_type=ContentTypeFactory(
                app_label='student'
            )
        )
        user.user_permissions.add(permission)
        headers = build_jwt_headers(user)
        self.assertTrue(self.test_user.has_usable_password())
        self.assert_activation_status(headers)

    def test_unauthorized_rejection(self):
        """
        Verify unauthorized users cannot deactivate accounts.
        """
        headers = build_jwt_headers(self.test_user)
        self.assert_activation_status(
            headers,
            expected_status=status.HTTP_403_FORBIDDEN,
            expected_activation_status=True
        )

    def test_on_jwt_headers_rejection(self):
        """
        Verify users who are not JWT authenticated are rejected.
        """
        UserFactory()
        self.assert_activation_status(
            {},
            expected_status=status.HTTP_401_UNAUTHORIZED,
            expected_activation_status=True
        )


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestDeactivateLogout(RetirementTestUserMixin, RetirementTestCase):
    """
    Tests the account deactivation/logout endpoint.
    """
    def setUp(self):
        super(TestDeactivateLogout, self).setUp()

        self.url = reverse('deactivate_logout')

    def build_post(self, password):
        return {'password': password}

    @mock.patch('openedx.core.djangolib.oauth2_retirement_utils')
    def test_user_can_deactivate_self(self, retirement_utils_mock):
        """
        Verify a user calling the deactivation endpoint logs out the user, deletes all their SSO tokens,
        and creates a user retirement row.
        """
        self.client.login(username=self.test_user.username, password=self.test_password)
        headers = build_jwt_headers(self.test_user)
        response = self.client.post(self.url, self.build_post(self.test_password), **headers)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # make sure the user model is as expected
        updated_user = User.objects.get(id=self.test_user.id)
        self.assertEqual(get_retired_email_by_email(self.test_user.email), updated_user.email)
        self.assertFalse(updated_user.has_usable_password())
        self.assertEqual(list(UserSocialAuth.objects.filter(user=self.test_user)), [])
        self.assertEqual(list(Registration.objects.filter(user=self.test_user)), [])
        self.assertEqual(len(UserRetirementStatus.objects.filter(user_id=self.test_user.id)), 1)
        # these retirement utils are tested elsewhere; just make sure we called them
        retirement_utils_mock.retire_dop_oauth2_models.assertCalledWith(self.test_user)
        retirement_utils_mock.retire_dot_oauth2_models.assertCalledWith(self.test_user)
        # make sure the user cannot log in
        self.assertFalse(self.client.login(username=self.test_user.username, password=self.test_password))
        # make sure that an email has been sent
        self.assertEqual(len(mail.outbox), 1)
        # ensure that it's been sent to the correct email address
        self.assertIn(self.test_user.email, mail.outbox[0].to)

    def test_password_mismatch(self):
        """
        Verify that the user submitting a mismatched password results in
        a rejection.
        """
        self.client.login(username=self.test_user.username, password=self.test_password)
        headers = build_jwt_headers(self.test_user)
        response = self.client.post(self.url, self.build_post(self.test_password + "xxxx"), **headers)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_called_twice(self):
        """
        Verify a user calling the deactivation endpoint a second time results in a "forbidden"
        error, as the user will be logged out.
        """
        self.client.login(username=self.test_user.username, password=self.test_password)
        headers = build_jwt_headers(self.test_user)
        response = self.client.post(self.url, self.build_post(self.test_password), **headers)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.client.login(username=self.test_user.username, password=self.test_password)
        headers = build_jwt_headers(self.test_user)
        response = self.client.post(self.url, self.build_post(self.test_password), **headers)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestDeactivateBySuperuser(RetirementTestUserMixin, RetirementTestCase):
    """
    Tests the account deactivation/logout endpoint used by Edraak admin.
    """
    def setUp(self):
        super(TestDeactivateBySuperuser, self).setUp()
        self.test_superuser_password = 'superuser_password'
        self.test_superuser = SuperuserFactory(password=self.test_superuser_password)

        self.url = reverse('deactivate')

    def _post(self, user, password, arguments):
        """
        Helper to post request using specific user login
        """
        self.client.login(username=user.username, password=password)
        headers = build_jwt_headers(user)
        return self.client.post(self.url, arguments, **headers)

    def test_deactivate_user(self):
        """
        Verify that calling the API will deactivate the user as expected. And don't double test the logic that is
        already tested in TestDeactivateLogout
        """
        response = self._post(
            user=self.test_superuser,
            password=self.test_superuser_password,
            arguments={'username': self.test_user.username}
        )
        # Verifying response
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # Verifying email sent (which indicates that everything went fine before that)
        self.assertIn(self.test_user.email, mail.outbox[0].to)

    def test_user_not_found(self):
        """
        Verify that a clear error will be returned if the provided username does not exist
        """
        response = self._post(
            user=self.test_superuser,
            password=self.test_superuser_password,
            arguments={'username': 'wrong'}
        )
        # Verifying response
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @ddt.data(SuperuserFactory, AdminFactory)
    def test_cannot_deactivate_superusers_or_staff(self, factory_class):
        """
        Verify that superusers cannot be deactivated
        """
        response = self._post(
            user=self.test_superuser,
            password=self.test_superuser_password,
            arguments={'username': factory_class().username}
        )
        # Verifying response
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_deactivate_retirement_worker(self):
        """
        Verify that superusers cannot be deactivated
        """
        with self.settings(RETIREMENT_SERVICE_WORKER_USERNAME=self.test_user.username):
            response = self._post(
                user=self.test_superuser,
                password=self.test_superuser_password,
                arguments={'username': self.test_user.username}
            )
        # Verifying response
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_permissions(self):
        """
        The view needs at least authentication and CanRetireUser
        """
        view_class = get_view_class_from_url(self.url)
        self.assertIn(permissions.IsAuthenticated, view_class.permission_classes)
        self.assertIn(CanRetireUser, view_class.permission_classes)


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestPartnerReportingCleanup(ModuleStoreTestCase):
    """
    Tests the partner reporting cleanup endpoint.
    """

    def setUp(self):
        super(TestPartnerReportingCleanup, self).setUp()
        self.test_superuser = SuperuserFactory()
        self.course = CourseFactory()
        self.course_awesome_org = CourseFactory(org='awesome_org')
        self.headers = build_jwt_headers(self.test_superuser)
        self.headers['content_type'] = "application/json"
        self.url = reverse('accounts_retirement_partner_report_cleanup')
        self.maxDiff = None

    def create_partner_reporting_statuses(self, is_being_processed=True, num=2):
        """
        Creates and returnes the given number of test users and UserRetirementPartnerReportingStatuses
        with the given is_being_processed value.
        """
        statuses = []
        for _ in range(num):
            user = UserFactory()
            reporting_status = UserRetirementPartnerReportingStatus.objects.create(
                user=user,
                original_username=user.username,
                original_email=user.email,
                original_name=user.first_name + ' ' + user.last_name,
                is_being_processed=is_being_processed
            )

            statuses.append(reporting_status)

        return statuses

    def assert_status_and_count(self, statuses, remaining_count, expected_status=status.HTTP_204_NO_CONTENT):
        """
        Performs a test client POST against the retirement reporting cleanup endpoint. It generates
        the JSON of usernames to clean up based on the given list of UserRetirementPartnerReportingStatuses,
        asserts that the given number of UserRetirementPartnerReportingStatus rows are still in the database
        after the operation, and asserts that the given expected_status HTTP status code is returned.
        """
        usernames = [{'original_username': u.original_username} for u in statuses]

        data = json.dumps(usernames)
        response = self.client.post(self.url, data=data, **self.headers)
        print(response)
        print(response.content)

        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(UserRetirementPartnerReportingStatus.objects.all().count(), remaining_count)

    def test_success(self):
        """
        A basic test that newly created UserRetirementPartnerReportingStatus rows are all deleted as expected.
        """
        statuses = self.create_partner_reporting_statuses()
        self.assert_status_and_count(statuses, remaining_count=0)

    def test_no_usernames(self):
        """
        Checks that if no usernames are passed in we will get a 400 back.
        """
        statuses = self.create_partner_reporting_statuses()
        self.assert_status_and_count([], len(statuses), expected_status=status.HTTP_400_BAD_REQUEST)

    def test_username_does_not_exist(self):
        """
        Checks that if a username is passed in that does not have a UserRetirementPartnerReportingStatus row
        we will get a 400 back.
        """
        statuses = self.create_partner_reporting_statuses()
        orig_count = len(statuses)

        # Create a bogus user that has a non-saved row. This user doesn't exist in the database, so
        # it should trigger the "incorrect number of rows" error.
        user = UserFactory()
        statuses.append(
            UserRetirementPartnerReportingStatus(
                user=user,
                original_username=user.username,
                original_email=user.email,
                original_name=user.first_name + ' ' + user.last_name,
                is_being_processed=True
            )
        )
        self.assert_status_and_count(statuses, orig_count, expected_status=status.HTTP_400_BAD_REQUEST)

    def test_username_in_wrong_status(self):
        """
        Checks that if an username passed in has the wrong "is_being_processed" value we will get a 400 error.
        """
        # Create some status rows in the expected status
        statuses = self.create_partner_reporting_statuses()

        # Create some users in the wrong processing status, should trigger the "incorrect number of rows" error.
        statuses += self.create_partner_reporting_statuses(is_being_processed=False)

        self.assert_status_and_count(statuses, len(statuses), expected_status=status.HTTP_400_BAD_REQUEST)

    def test_does_not_delete_users_in_process(self):
        """
        Checks that with mixed "is_being_processed" values in the table only the usernames passed in will
        be deleted.
        """
        statuses = self.create_partner_reporting_statuses()

        self.create_partner_reporting_statuses(is_being_processed=False)
        self.assert_status_and_count(statuses, len(statuses))


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestPartnerReportingPut(RetirementTestCase, ModuleStoreTestCase):
    """
    Tests the partner reporting list endpoint
    """

    def setUp(self):
        super(TestPartnerReportingPut, self).setUp()
        self.test_superuser = SuperuserFactory()
        self.course = CourseFactory()
        self.course_awesome_org = CourseFactory(org='awesome_org')
        self.courses = (self.course, self.course_awesome_org)
        self.headers = build_jwt_headers(self.test_superuser)
        self.url = reverse('accounts_retirement_partner_report')
        self.headers['content_type'] = "application/json"
        self.maxDiff = None
        self.partner_queue_state = RetirementState.objects.get(state_name='ADDING_TO_PARTNER_QUEUE')

    def put_and_assert_status(self, data, expected_status=status.HTTP_204_NO_CONTENT):
        """
        Helper function for making a request to the retire subscriptions endpoint, and asserting the status.
        """
        response = self.client.put(self.url, json.dumps(data), **self.headers)
        self.assertEqual(response.status_code, expected_status)
        return response

    def test_success(self):
        """
        Checks the simple success case of creating a user, enrolling in a course, and doing the partner
        report PUT. User should then have the appropriate row in UserRetirementPartnerReportingStatus
        """
        retirement = create_retirement_status(UserFactory(), state=self.partner_queue_state)
        for course in self.courses:
            CourseEnrollment.enroll(user=retirement.user, course_key=course.id)

        self.put_and_assert_status({'username': retirement.original_username})
        self.assertTrue(UserRetirementPartnerReportingStatus.objects.filter(user=retirement.user).exists())

    def test_idempotent(self):
        """
        Runs the success test twice to make sure that re-running the step still succeeds.
        """
        retirement = create_retirement_status(UserFactory(), state=self.partner_queue_state)
        for course in self.courses:
            CourseEnrollment.enroll(user=retirement.user, course_key=course.id)

        # Do our step
        self.put_and_assert_status({'username': retirement.original_username})

        # Do our basic other retirement step fakery
        fake_completed_retirement(retirement.user)

        # Try running our step again
        self.put_and_assert_status({'username': retirement.original_username})
        self.assertTrue(UserRetirementPartnerReportingStatus.objects.filter(user=retirement.user).exists())

    def test_unknown_user(self):
        """
        Checks that a username with no active retirement generates a 404
        """
        user = UserFactory()
        for course in self.courses:
            CourseEnrollment.enroll(user=user, course_key=course.id)

        self.put_and_assert_status({'username': user.username}, status.HTTP_404_NOT_FOUND)

    def test_nonexistent_course(self):
        """
        Checks that if a user has been enrolled in a course that does not exist
        (we allow this!) we can still get their orgs for partner reporting. This
        prevents regressions of a bug we found in prod where users in this state
        were throwing 500 errors when _get_orgs_for_user hit the database to find
        the enrollment.course.org. We now just use the enrollment.course_id.org
        since for this purpose we don't care if the course exists.
        """
        retirement = create_retirement_status(UserFactory(), state=self.partner_queue_state)
        user = retirement.user
        enrollment = CourseEnrollment.enroll(user=user, course_key=CourseKey.from_string('edX/Test201/2018_Fall'))

        # Make sure the enrollment was created
        self.assertTrue(enrollment.is_active)

        # Make sure the correct org is found and returned from the low-level call. We don't get back
        # the orgs from our PUT operation, so this is the best way to make sure it's doing the right
        # thing.
        orgs = AccountRetirementPartnerReportView._get_orgs_for_user(user)  # pylint: disable=protected-access
        self.assertTrue(len(orgs) == 1)
        self.assertTrue('edX' in orgs)

        # PUT should succeed
        self.put_and_assert_status({'username': user.username})

        # Row should exist
        self.assertTrue(UserRetirementPartnerReportingStatus.objects.filter(user=retirement.user).exists())


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestPartnerReportingList(ModuleStoreTestCase):
    """
    Tests the partner reporting list endpoint
    """

    def setUp(self):
        super(TestPartnerReportingList, self).setUp()
        self.test_superuser = SuperuserFactory()
        self.course = CourseFactory()
        self.course_awesome_org = CourseFactory(org='awesome_org')
        self.courses = (self.course, self.course_awesome_org)
        self.headers = build_jwt_headers(self.test_superuser)
        self.url = reverse('accounts_retirement_partner_report')
        self.maxDiff = None
        self.test_created_datetime = datetime.datetime(2018, 1, 1, tzinfo=pytz.UTC)

    def get_user_dict(self, user, enrollments):
        """
        Emulate the DRF serialization to create a dict we can compare against the partner
        reporting list endpoint results. If this breaks in testing the serialization will
        have changed and clients of this endpoint will need to be updates as well.
        """
        return {
            'user_id': user.pk,
            'original_username': user.username,
            'original_email': user.email,
            'original_name': user.first_name + ' ' + user.last_name,
            'orgs': [enrollment.course.org for enrollment in enrollments],
            # using ISO format with "Z" is the way DRF serializes datetimes by default
            'created': self.test_created_datetime.isoformat().replace('+00:00', 'Z'),
        }

    def create_partner_reporting_statuses(self, is_being_processed=False, num=2, courses=None):
        """
        Create the given number of test users and UserRetirementPartnerReportingStatus rows,
        enroll them in the given course (or the default test course if none given), and set
        their processing state to "is_being_processed".

        Returns a list of user dicts representing what we would expect back from the
        endpoint for the given user / enrollment.
        """
        user_dicts = []
        courses = self.courses if courses is None else courses

        for _ in range(num):
            user = UserFactory()
            UserRetirementPartnerReportingStatus.objects.create(
                user=user,
                original_username=user.username,
                original_email=user.email,
                original_name=user.first_name + ' ' + user.last_name,
                is_being_processed=is_being_processed,
                created=self.test_created_datetime,
            )

            enrollments = []
            for course in courses:
                enrollments.append(CourseEnrollment.enroll(user=user, course_key=course.id))

            user_dicts.append(
                self.get_user_dict(user, enrollments)
            )

        return user_dicts

    def assert_status_and_user_list(self, expected_users, expected_status=status.HTTP_200_OK):
        """
        Makes the partner reporting list POST and asserts that the given users are
        in the returned list, as well as asserting the expected HTTP status code
        is returned.
        """
        response = self.client.post(self.url, **self.headers)
        self.assertEqual(response.status_code, expected_status)

        returned_users = response.json()
        print(returned_users)
        print(expected_users)

        self.assertEqual(len(expected_users), len(returned_users))

        # These sub-lists will fail assertCountEqual if they're out of order
        for expected_user in expected_users:
            expected_user['orgs'].sort()

        for returned_user in returned_users:
            returned_user['orgs'].sort()

        self.assertCountEqual(returned_users, expected_users)

    def test_success(self):
        """
        Basic test to make sure that users in two different orgs are returned.
        """
        users = self.create_partner_reporting_statuses()
        users += self.create_partner_reporting_statuses(courses=(self.course_awesome_org,))

        self.assert_status_and_user_list(users)

    def test_success_multiple_statuses(self):
        """
        Checks that only users in the correct is_being_processed state (False) are returned.
        """
        users = self.create_partner_reporting_statuses()

        # These should not come back
        self.create_partner_reporting_statuses(courses=(self.course_awesome_org,), is_being_processed=True)

        self.assert_status_and_user_list(users)

    def test_no_users(self):
        """
        Checks that the call returns a success code and empty list if no users are found.
        """
        self.assert_status_and_user_list([])

    def test_only_users_in_processing(self):
        """
        Checks that the call returns a success code and empty list if only users with
        "is_being_processed=True" are in the database.
        """
        self.create_partner_reporting_statuses(is_being_processed=True)
        self.assert_status_and_user_list([])

    def test_state_update(self):
        """
        Checks that users are progressed to "is_being_processed" True upon being returned
        from this call.
        """
        users = self.create_partner_reporting_statuses()

        # First time through we should get the users
        self.assert_status_and_user_list(users)

        # Second time they should be updated to is_being_processed=True
        self.assert_status_and_user_list([])


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestAccountRetirementList(RetirementTestCase):
    """
    Tests the account retirement endpoint.
    """

    def setUp(self):
        super(TestAccountRetirementList, self).setUp()
        self.test_superuser = SuperuserFactory()
        self.headers = build_jwt_headers(self.test_superuser)
        self.url = reverse('accounts_retirement_queue')
        self.maxDiff = None

    def assert_status_and_user_list(
            self,
            expected_data,
            expected_status=status.HTTP_200_OK,
            states_to_request=None,
            cool_off_days=7
    ):
        """
        Helper function for making a request to the retire subscriptions endpoint, asserting the status, and
        optionally asserting data returned.
        """
        if states_to_request is None:
            # These are just a couple of random states that should be used in any implementation
            states_to_request = ['PENDING', 'LOCKING_ACCOUNT']
        else:
            # Can pass in RetirementState objects or strings here
            try:
                states_to_request = [s.state_name for s in states_to_request]
            except AttributeError:
                states_to_request = states_to_request

        data = {'cool_off_days': cool_off_days, 'states': states_to_request}
        response = self.client.get(self.url, data, **self.headers)
        self.assertEqual(response.status_code, expected_status)
        response_data = response.json()

        if expected_data:
            # These datetimes won't match up due to serialization, but they're inherited fields tested elsewhere
            for data in (response_data, expected_data):
                for retirement in data:
                    del retirement['created']
                    del retirement['modified']

            self.assertItemsEqual(response_data, expected_data)

    def test_empty(self):
        """
        Verify that an empty array is returned if no users are awaiting retirement
        """
        self.assert_status_and_user_list([])

    def test_users_exist_none_in_correct_status(self):
        """
        Verify that users in dead end states are not returned
        """
        for state in self._get_dead_end_states():
            create_retirement_status(UserFactory(), state=state)
        self.assert_status_and_user_list([], states_to_request=self._get_non_dead_end_states())

    def test_users_retrieved_in_multiple_states(self):
        """
        Verify that if multiple states are requested, learners in each state are returned.
        """
        multiple_states = ['PENDING', 'FORUMS_COMPLETE']
        for state in multiple_states:
            create_retirement_status(UserFactory(), state=RetirementState.objects.get(state_name=state))
        data = {'cool_off_days': 0, 'states': multiple_states}
        response = self.client.get(self.url, data, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 2)

    def test_users_exist(self):
        """
        Verify users in different states are returned with correct data or filtered out
        """
        self.maxDiff = None
        retirement_values = []
        states_to_request = []

        dead_end_states = self._get_dead_end_states()

        for retirement in self._create_users_all_states():
            if retirement.current_state not in dead_end_states:
                states_to_request.append(retirement.current_state)
                retirement_values.append(self._retirement_to_dict(retirement))

        self.assert_status_and_user_list(retirement_values, states_to_request=self._get_non_dead_end_states())

    def test_date_filter(self):
        """
        Verifies the functionality of the `cool_off_days` parameter by creating 1 retirement per day for
        10 days. Then requests different 1-10 `cool_off_days` to confirm the correct retirements are returned.
        """
        retirements = []
        days_back_to_test = 10

        # Create a retirement per day for the last 10 days, from oldest date to newest. We want these all created
        # before we start checking, thus the two loops.
        # retirements = [2018-04-10..., 2018-04-09..., 2018-04-08...]
        pending_state = RetirementState.objects.get(state_name='PENDING')
        for days_back in range(1, days_back_to_test, -1):
            create_datetime = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=days_back)
            retirements.append(create_retirement_status(
                UserFactory(),
                state=pending_state,
                create_datetime=create_datetime
            ))

        # Confirm we get the correct number and data back for each day we add to cool off days
        # For each day we add to `cool_off_days` we expect to get one fewer retirement.
        for cool_off_days in range(1, days_back_to_test):
            # Start with 9 days back
            req_days_back = days_back_to_test - cool_off_days

            retirement_dicts = [self._retirement_to_dict(ret) for ret in retirements[:cool_off_days]]

            self.assert_status_and_user_list(
                retirement_dicts,
                cool_off_days=req_days_back
            )

    def test_bad_cool_off_days(self):
        """
        Check some bad inputs to make sure we get back the expected status
        """
        self.assert_status_and_user_list(None, expected_status=status.HTTP_400_BAD_REQUEST, cool_off_days=-1)
        self.assert_status_and_user_list(None, expected_status=status.HTTP_400_BAD_REQUEST, cool_off_days='ABCDERTP')

    def test_bad_states(self):
        """
        Check some bad inputs to make sure we get back the expected status
        """
        self.assert_status_and_user_list(
            None,
            expected_status=status.HTTP_400_BAD_REQUEST,
            states_to_request=['TUNA', 'TACO'])
        self.assert_status_and_user_list(None, expected_status=status.HTTP_400_BAD_REQUEST, states_to_request=[])

    def test_missing_params(self):
        """
        All params are required, make sure that is enforced
        """
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(self.url, {}, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(self.url, {'cool_off_days': 7}, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        RetirementState.objects.get(state_name='PENDING')
        response = self.client.get(self.url, {'states': ['PENDING']}, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestAccountRetirementsByStatusAndDate(RetirementTestCase):
    """
    Tests the retirements_by_status_and_date endpoint
    """

    def setUp(self):
        super(TestAccountRetirementsByStatusAndDate, self).setUp()
        self.test_superuser = SuperuserFactory()
        self.headers = build_jwt_headers(self.test_superuser)
        self.url = reverse('accounts_retirements_by_status_and_date')
        self.maxDiff = None

    def assert_status_and_user_list(
            self,
            expected_data,
            expected_status=status.HTTP_200_OK,
            state_to_request=None,
            start_date=None,
            end_date=None
    ):
        """
        Helper function for making a request to the endpoint, asserting the status, and
        optionally asserting data returned. Will try to convert datetime start and end dates
        to the correct string formatting.
        """
        if state_to_request is None:
            state_to_request = 'COMPLETE'

        if start_date is None:
            start_date = datetime.datetime.now().date().strftime('%Y-%m-%d')
        else:
            start_date = start_date.date().strftime('%Y-%m-%d')

        if end_date is None:
            end_date = datetime.datetime.now().date().strftime('%Y-%m-%d')
        else:
            end_date = end_date.date().strftime('%Y-%m-%d')

        data = {'start_date': start_date, 'end_date': end_date, 'state': state_to_request}
        response = self.client.get(self.url, data, **self.headers)

        print(response.status_code)
        print(response)

        self.assertEqual(response.status_code, expected_status)
        response_data = response.json()

        if expected_data:
            # These datetimes won't match up due to serialization, but they're inherited fields tested elsewhere
            for data in (response_data, expected_data):
                for retirement in data:
                    # These may have been deleted in a previous pass
                    try:
                        del retirement['created']
                        del retirement['modified']
                    except KeyError:
                        pass

            self.assertItemsEqual(response_data, expected_data)

    def test_empty(self):
        """
        Verify that an empty array is returned if no users are awaiting retirement
        """
        self.assert_status_and_user_list([])

    def test_users_exist_none_in_correct_state(self):
        """
        Verify that users in non-requested states are not returned
        """
        state = RetirementState.objects.get(state_name='PENDING')
        create_retirement_status(UserFactory(), state=state)
        self.assert_status_and_user_list([])

    def test_users_exist(self):
        """
        Verify correct user is returned when users in different states exist
        """
        # Stores the user we expect to get back
        retirement_values = None
        for retirement in self._create_users_all_states():
            if retirement.current_state == 'COMPLETE':
                retirement_values.append(self._retirement_to_dict(retirement))

        self.assert_status_and_user_list(retirement_values)

    def test_bad_states(self):
        """
        Check some bad inputs to make sure we get back the expected status
        """
        self.assert_status_and_user_list(None, expected_status=status.HTTP_400_BAD_REQUEST, state_to_request='TACO')

    def test_date_filter(self):
        """
        Verifies the functionality of the start and end date filters
        """
        retirements = []
        complete_state = RetirementState.objects.get(state_name='COMPLETE')

        # Create retirements for the last 10 days
        for days_back in range(0, 10):
            create_datetime = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=days_back)
            ret = create_retirement_status(UserFactory(), state=complete_state, create_datetime=create_datetime)
            retirements.append(self._retirement_to_dict(ret))

        # Go back in time adding days to the query, assert the correct retirements are present
        end_date = datetime.datetime.now(pytz.UTC)
        for days_back in range(1, 11):
            retirement_dicts = retirements[:days_back]
            start_date = end_date - datetime.timedelta(days=days_back - 1)
            self.assert_status_and_user_list(
                retirement_dicts,
                start_date=start_date,
                end_date=end_date
            )

    def test_bad_dates(self):
        """
        Check some bad inputs to make sure we get back the expected status
        """
        good_date = '2018-01-01'
        for bad_param, good_param in (('start_date', 'end_date'), ('end_date', 'start_date')):
            for bad_date in ('10/21/2001', '2118-01-01', '2018-14-25', 'toast', 5):
                data = {
                    bad_param: bad_date,
                    good_param: good_date,
                    'state': 'COMPLETE'
                }
                response = self.client.get(self.url, data, **self.headers)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @ddt.data(
        {},
        {'start_date': '2018-01-01'},
        {'end_date': '2018-01-01'},
        {'state': 'PENDING'},
        {'start_date': '2018-01-01', 'state': 'PENDING'},
        {'end_date': '2018-01-01', 'state': 'PENDING'},
    )
    def test_missing_params(self, request_data):
        """
        All params are required, make sure that is enforced
        """
        response = self.client.get(self.url, request_data, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestAccountRetirementRetrieve(RetirementTestCase):
    """
    Tests the account retirement retrieval endpoint.
    """
    def setUp(self):
        super(TestAccountRetirementRetrieve, self).setUp()
        self.test_user = UserFactory()
        self.test_superuser = SuperuserFactory()
        self.url = reverse('accounts_retirement_retrieve', kwargs={'username': self.test_user.username})
        self.headers = build_jwt_headers(self.test_superuser)
        self.maxDiff = None

    def assert_status_and_user_data(self, expected_data, expected_status=status.HTTP_200_OK, username_to_find=None):
        """
        Helper function for making a request to the retire subscriptions endpoint, asserting the status,
        and optionally asserting the expected data.
        """
        if username_to_find is not None:
            self.url = reverse('accounts_retirement_retrieve', kwargs={'username': username_to_find})

        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, expected_status)

        if expected_data is not None:
            response_data = response.json()

            # These won't match up due to serialization, but they're inherited fields tested elsewhere
            for data in (expected_data, response_data):
                del data['created']
                del data['modified']

            self.assertDictEqual(response_data, expected_data)
            return response_data

    def test_no_retirement(self):
        """
        Confirm we get a 404 if a retirement for the user can be found
        """
        self.assert_status_and_user_data(None, status.HTTP_404_NOT_FOUND)

    def test_retirements_all_states(self):
        """
        Create a bunch of retirements and confirm we get back the correct data for each
        """
        retirements = []

        for state in RetirementState.objects.all():
            retirements.append(create_retirement_status(UserFactory(), state=state))

        for retirement in retirements:
            values = self._retirement_to_dict(retirement)
            self.assert_status_and_user_data(values, username_to_find=values['user']['username'])

    def test_retrieve_by_old_username(self):
        """
        Simulate retrieving a retirement by the old username, after the name has been changed to the hashed one
        """
        pending_state = RetirementState.objects.get(state_name='PENDING')
        retirement = create_retirement_status(UserFactory(), state=pending_state)
        original_username = retirement.user.username

        hashed_username = get_retired_username_by_username(original_username)

        retirement.user.username = hashed_username
        retirement.user.save()

        values = self._retirement_to_dict(retirement)
        self.assert_status_and_user_data(values, username_to_find=original_username)


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestAccountRetirementCleanup(RetirementTestCase):
    """
    Tests the account retirement cleanup endpoint.
    """
    def setUp(self):
        super(TestAccountRetirementCleanup, self).setUp()
        self.pending_state = RetirementState.objects.get(state_name='PENDING')
        self.complete_state = RetirementState.objects.get(state_name='COMPLETE')
        self.retirements = []
        self.usernames = []

        for _ in range(1, 10):
            user = UserFactory()
            self.retirements.append(create_retirement_status(user, state=self.complete_state))
            self.usernames.append(user.username)

        self.test_superuser = SuperuserFactory()
        self.headers = build_jwt_headers(self.test_superuser)
        self.headers['content_type'] = "application/json"
        self.url = reverse('accounts_retirement_cleanup')

    def cleanup_and_assert_status(self, data=None, expected_status=status.HTTP_204_NO_CONTENT):
        """
        Helper function for making a request to the retirement cleanup endpoint, and asserting the status.
        """
        if data is None:
            data = {'usernames': self.usernames}

        response = self.client.post(self.url, json.dumps(data), **self.headers)
        print(response)
        self.assertEqual(response.status_code, expected_status)
        return response

    def test_simple_success(self):
        self.cleanup_and_assert_status()
        self.assertFalse(UserRetirementStatus.objects.all())

    def test_leaves_other_users(self):
        remaining_usernames = []

        # Create a bunch of local users in different states
        for state in (self.pending_state, self.complete_state):
            for _ in range(1, 3):
                user = UserFactory()
                remaining_usernames.append(create_retirement_status(user, state=state).user.username)

        # Call should succeed and leave behind the local users in both states
        self.cleanup_and_assert_status()
        self.assertEqual(
            UserRetirementStatus.objects.filter(user__username__in=remaining_usernames).count(),
            len(remaining_usernames)
        )

    def test_no_usernames(self):
        self.cleanup_and_assert_status(data={'usernames': []})

    def test_bad_usernames(self):
        self.cleanup_and_assert_status(data={'usernames': 'foo'}, expected_status=status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_username(self):
        self.cleanup_and_assert_status(
            data={'usernames': self.usernames + ['does not exist']},
            expected_status=status.HTTP_400_BAD_REQUEST
        )

    def test_username_bad_state(self):
        # Set one of the users we're looking up to a non-COMPLETE state to
        # force the error
        retirement = UserRetirementStatus.objects.get(user__username=self.usernames[0])
        retirement.current_state = self.pending_state
        retirement.save()

        self.cleanup_and_assert_status(expected_status=status.HTTP_400_BAD_REQUEST)


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestAccountRetirementUpdate(RetirementTestCase):
    """
    Tests the account retirement endpoint.
    """
    def setUp(self):
        super(TestAccountRetirementUpdate, self).setUp()
        self.pending_state = RetirementState.objects.get(state_name='PENDING')
        self.locking_state = RetirementState.objects.get(state_name='LOCKING_ACCOUNT')

        self.retirement = create_retirement_status(UserFactory(), state=self.pending_state)
        self.test_user = self.retirement.user
        self.test_superuser = SuperuserFactory()
        self.headers = build_jwt_headers(self.test_superuser)
        self.headers['content_type'] = "application/json"
        self.url = reverse('accounts_retirement_update')

    def update_and_assert_status(self, data, expected_status=status.HTTP_204_NO_CONTENT):
        """
        Helper function for making a request to the retire subscriptions endpoint, and asserting the status.
        """
        if 'username' not in data:
            data['username'] = self.test_user.username

        response = self.client.patch(self.url, json.dumps(data), **self.headers)
        self.assertEqual(response.status_code, expected_status)

    def test_single_update(self):
        """
        Basic test to confirm changing state works and saves the given response
        """
        data = {'new_state': 'LOCKING_ACCOUNT', 'response': 'this should succeed'}
        self.update_and_assert_status(data)

        # Refresh the retirment object and confirm the messages and state are correct
        retirement = UserRetirementStatus.objects.get(id=self.retirement.id)
        self.assertEqual(retirement.current_state, RetirementState.objects.get(state_name='LOCKING_ACCOUNT'))
        self.assertEqual(retirement.last_state, RetirementState.objects.get(state_name='PENDING'))
        self.assertIn('this should succeed', retirement.responses)

    def test_move_through_process(self):
        """
        Simulate moving a retirement through the process and confirm they end up in the
        correct state, with all relevant response messages logged.
        """
        fake_retire_process = [
            {'new_state': 'LOCKING_ACCOUNT', 'response': 'accountlockstart'},
            {'new_state': 'LOCKING_COMPLETE', 'response': 'accountlockcomplete'},
            {'new_state': 'RETIRING_CREDENTIALS', 'response': 'retiringcredentials'},
            {'new_state': 'CREDENTIALS_COMPLETE', 'response': 'credentialsretired'},
            {'new_state': 'COMPLETE', 'response': 'accountretirementcomplete'},
        ]

        for update_data in fake_retire_process:
            self.update_and_assert_status(update_data)

        # Refresh the retirment object and confirm the messages and state are correct
        retirement = UserRetirementStatus.objects.get(id=self.retirement.id)
        self.assertEqual(retirement.current_state, RetirementState.objects.get(state_name='COMPLETE'))
        self.assertEqual(retirement.last_state, RetirementState.objects.get(state_name='CREDENTIALS_COMPLETE'))
        self.assertIn('accountlockstart', retirement.responses)
        self.assertIn('accountlockcomplete', retirement.responses)
        self.assertIn('retiringcredentials', retirement.responses)
        self.assertIn('credentialsretired', retirement.responses)
        self.assertIn('accountretirementcomplete', retirement.responses)

    def test_unknown_state(self):
        """
        Test that trying to set to an unknown state fails with a 400
        """
        data = {'new_state': 'BOGUS_STATE', 'response': 'this should fail'}
        self.update_and_assert_status(data, status.HTTP_400_BAD_REQUEST)

    def test_bad_vars(self):
        """
        Test various ways of sending the wrong variables to make sure they all fail correctly
        """
        # No `new_state`
        data = {'response': 'this should fail'}
        self.update_and_assert_status(data, status.HTTP_400_BAD_REQUEST)

        # No `response`
        data = {'new_state': 'COMPLETE'}
        self.update_and_assert_status(data, status.HTTP_400_BAD_REQUEST)

        # Unknown `new_state`
        data = {'new_state': 'BOGUS_STATE', 'response': 'this should fail'}
        self.update_and_assert_status(data, status.HTTP_400_BAD_REQUEST)

        # No `new_state` or `response`
        data = {}
        self.update_and_assert_status(data, status.HTTP_400_BAD_REQUEST)

        # Unexpected param `should_not_exist`
        data = {'should_not_exist': 'bad', 'new_state': 'COMPLETE', 'response': 'this should fail'}
        self.update_and_assert_status(data, status.HTTP_400_BAD_REQUEST)

    def test_no_retirement(self):
        """
        Confirm that trying to operate on a non-existent retirement for an existing user 404s
        """
        # Delete the only retirement, created in setUp
        UserRetirementStatus.objects.all().delete()
        data = {'new_state': 'LOCKING_ACCOUNT', 'response': 'this should fail'}
        self.update_and_assert_status(data, status.HTTP_404_NOT_FOUND)

    def test_no_user(self):
        """
        Confirm that trying to operate on a non-existent user 404s
        """
        data = {'new_state': 'LOCKING_ACCOUNT', 'response': 'this should fail', 'username': 'does not exist'}
        self.update_and_assert_status(data, status.HTTP_404_NOT_FOUND)

    @ddt.data(
        # Test moving backward from intermediate state
        ('LOCKING_ACCOUNT', 'PENDING', False, status.HTTP_400_BAD_REQUEST),
        ('LOCKING_ACCOUNT', 'PENDING', True, status.HTTP_204_NO_CONTENT),

        # Test moving backward from dead end state
        ('COMPLETE', 'PENDING', False, status.HTTP_400_BAD_REQUEST),
        ('COMPLETE', 'PENDING', True, status.HTTP_204_NO_CONTENT),

        # Test moving to the same state
        ('LOCKING_ACCOUNT', 'LOCKING_ACCOUNT', False, status.HTTP_400_BAD_REQUEST),
        ('LOCKING_ACCOUNT', 'LOCKING_ACCOUNT', True, status.HTTP_204_NO_CONTENT),
    )
    @ddt.unpack
    def test_moves(self, start_state, move_to_state, force, expected_response_code):
        retirement = UserRetirementStatus.objects.get(id=self.retirement.id)
        retirement.current_state = RetirementState.objects.get(state_name=start_state)
        retirement.save()

        data = {'new_state': move_to_state, 'response': 'foo'}

        if force:
            data['force'] = True

        self.update_and_assert_status(data, expected_response_code)


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestAccountRetirementPost(RetirementTestCase):
    """
    Tests the account retirement endpoint.
    """
    def setUp(self):
        super(TestAccountRetirementPost, self).setUp()

        self.test_user = UserFactory()
        self.test_superuser = SuperuserFactory()
        self.original_username = self.test_user.username
        self.original_email = self.test_user.email
        self.retired_username = get_retired_username_by_username(self.original_username)
        self.retired_email = get_retired_email_by_email(self.original_email)

        retirement_state = RetirementState.objects.get(state_name='RETIRING_LMS')
        self.retirement_status = UserRetirementStatus.create_retirement(self.test_user)
        self.retirement_status.current_state = retirement_state
        self.retirement_status.last_state = retirement_state
        self.retirement_status.save()

        SocialLink.objects.create(
            user_profile=self.test_user.profile,
            platform='Facebook',
            social_link='www.facebook.com'
        ).save()

        self.cache_key = UserProfile.country_cache_key_name(self.test_user.id)
        cache.set(self.cache_key, 'Timor-leste')

        # Enterprise model setup
        self.course_id = 'course-v1:edX+DemoX.1+2T2017'
        self.enterprise_customer = EnterpriseCustomer.objects.create(
            name='test_enterprise_customer',
            site=SiteFactory.create()
        )
        self.enterprise_user = EnterpriseCustomerUser.objects.create(
            enterprise_customer=self.enterprise_customer,
            user_id=self.test_user.id,
        )
        self.enterprise_enrollment = EnterpriseCourseEnrollment.objects.create(
            enterprise_customer_user=self.enterprise_user,
            course_id=self.course_id
        )
        self.pending_enterprise_user = PendingEnterpriseCustomerUser.objects.create(
            enterprise_customer_id=self.enterprise_user.enterprise_customer_id,
            user_email=self.test_user.email
        )
        self.sapsf_audit = SapSuccessFactorsLearnerDataTransmissionAudit.objects.create(
            sapsf_user_id=self.test_user.id,
            enterprise_course_enrollment_id=self.enterprise_enrollment.id,
            completed_timestamp=1,
        )
        self.consent = DataSharingConsent.objects.create(
            username=self.test_user.username,
            enterprise_customer=self.enterprise_customer,
        )

        # Entitlement model setup
        self.entitlement = CourseEntitlementFactory.create(user=self.test_user)
        self.entitlement_support_detail = CourseEntitlementSupportDetail.objects.create(
            entitlement=self.entitlement,
            support_user=UserFactory(),
            comments='A comment containing potential PII.'
        )

        # Misc. setup
        PendingEmailChangeFactory.create(user=self.test_user)
        UserOrgTagFactory.create(user=self.test_user, key='foo', value='bar')
        UserOrgTagFactory.create(user=self.test_user, key='cat', value='dog')

        CourseEnrollmentAllowedFactory.create(email=self.original_email)

        self.course_key = CourseKey.from_string('course-v1:edX+DemoX+Demo_Course')
        self.cohort = CourseUserGroup.objects.create(
            name="TestCohort",
            course_id=self.course_key,
            group_type=CourseUserGroup.COHORT
        )
        self.cohort_assignment = UnregisteredLearnerCohortAssignments.objects.create(
            course_user_group=self.cohort,
            course_id=self.course_key,
            email=self.original_email
        )

        # setup for doing POST from test client
        self.headers = build_jwt_headers(self.test_superuser)
        self.headers['content_type'] = "application/json"
        self.url = reverse('accounts_retire')

    def post_and_assert_status(self, data, expected_status=status.HTTP_204_NO_CONTENT):
        """
        Helper function for making a request to the retire subscriptions endpoint, and asserting the status.
        """
        response = self.client.post(self.url, json.dumps(data), **self.headers)
        self.assertEqual(response.status_code, expected_status)
        return response

    def test_user_profile_pii_has_expected_values(self):
        expected_user_profile_pii = {
            'name': '',
            'meta': '',
            'location': '',
            'year_of_birth': None,
            'gender': None,
            'mailing_address': None,
            'city': None,
            'country': None,
            'bio': None,
        }
        self.assertEqual(expected_user_profile_pii, USER_PROFILE_PII)

    def test_retire_user_server_error_is_raised(self):
        path = 'openedx.core.djangoapps.user_api.models.UserRetirementStatus.get_retirement_for_retirement_action'
        with mock.patch(path, side_effect=Exception('Unexpected Exception')) as mock_get_retirement:
            data = {'username': self.test_user.username}
            response = self.post_and_assert_status(data, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual('Unexpected Exception', text_type(response.json()))
            mock_get_retirement.assert_called_once_with(self.original_username)

    def test_retire_user_where_user_already_retired(self):
        path = 'openedx.core.djangoapps.user_api.accounts.views.is_username_retired'
        with mock.patch(path, return_value=True) as mock_is_username_retired:
            data = {'username': self.test_user.username}
            response = self.post_and_assert_status(data, status.HTTP_204_NO_CONTENT)
            self.assertFalse(response.content)
            mock_is_username_retired.assert_not_called()

    def test_retire_user_where_username_not_provided(self):
        response = self.post_and_assert_status({}, status.HTTP_404_NOT_FOUND)
        expected_response_message = {'message': text_type('The user was not specified.')}
        self.assertEqual(expected_response_message, response.json())

    @mock.patch('openedx.core.djangoapps.user_api.accounts.views.get_profile_image_names')
    @mock.patch('openedx.core.djangoapps.user_api.accounts.views.remove_profile_images')
    def test_retire_user(self, mock_remove_profile_images, mock_get_profile_image_names):
        data = {'username': self.original_username}
        self.post_and_assert_status(data)

        self.test_user.refresh_from_db()
        self.test_user.profile.refresh_from_db()  # pylint: disable=no-member

        expected_user_values = {
            'first_name': '',
            'last_name': '',
            'is_active': False,
            'username': self.retired_username,
        }
        for field, expected_value in iteritems(expected_user_values):
            self.assertEqual(expected_value, getattr(self.test_user, field))

        for field, expected_value in iteritems(USER_PROFILE_PII):
            self.assertEqual(expected_value, getattr(self.test_user.profile, field))

        self.assertIsNone(self.test_user.profile.profile_image_uploaded_at)
        mock_get_profile_image_names.assert_called_once_with(self.original_username)
        mock_remove_profile_images.assert_called_once_with(
            mock_get_profile_image_names.return_value
        )

        self.assertFalse(
            SocialLink.objects.filter(user_profile=self.test_user.profile).exists()
        )

        self.assertIsNone(cache.get(self.cache_key))

        self._data_sharing_consent_assertions()
        self._sapsf_audit_assertions()
        self._pending_enterprise_customer_user_assertions()
        self._entitlement_support_detail_assertions()

        self.assertFalse(PendingEmailChange.objects.filter(user=self.test_user).exists())
        self.assertFalse(UserOrgTag.objects.filter(user=self.test_user).exists())

        self.assertFalse(CourseEnrollmentAllowed.objects.filter(email=self.original_email).exists())
        self.assertFalse(UnregisteredLearnerCohortAssignments.objects.filter(email=self.original_email).exists())

    def test_retire_user_twice_idempotent(self):
        data = {'username': self.original_username}
        self.post_and_assert_status(data)
        fake_completed_retirement(self.test_user)
        self.post_and_assert_status(data)

    def test_deletes_pii_from_user_profile(self):
        for model_field, value_to_assign in iteritems(USER_PROFILE_PII):
            if value_to_assign == '':
                value = 'foo'
            else:
                value = mock.Mock()
            setattr(self.test_user.profile, model_field, value)

        AccountRetirementView.clear_pii_from_userprofile(self.test_user)

        for model_field, value_to_assign in iteritems(USER_PROFILE_PII):
            self.assertEqual(value_to_assign, getattr(self.test_user.profile, model_field))

        social_links = SocialLink.objects.filter(
            user_profile=self.test_user.profile
        )
        self.assertFalse(social_links.exists())

    @mock.patch('openedx.core.djangoapps.user_api.accounts.views.get_profile_image_names')
    @mock.patch('openedx.core.djangoapps.user_api.accounts.views.remove_profile_images')
    def test_removes_user_profile_images(
        self, mock_remove_profile_images, mock_get_profile_image_names
    ):
        test_datetime = datetime.datetime(2018, 1, 1)
        self.test_user.profile.profile_image_uploaded_at = test_datetime

        AccountRetirementView.delete_users_profile_images(self.test_user)

        self.test_user.profile.refresh_from_db()  # pylint: disable=no-member

        self.assertIsNone(self.test_user.profile.profile_image_uploaded_at)
        mock_get_profile_image_names.assert_called_once_with(self.test_user.username)
        mock_remove_profile_images.assert_called_once_with(
            mock_get_profile_image_names.return_value
        )

    def test_can_delete_user_profiles_country_cache(self):
        AccountRetirementView.delete_users_country_cache(self.test_user)
        self.assertIsNone(cache.get(self.cache_key))

    def test_can_retire_users_datasharingconsent(self):
        AccountRetirementView.retire_users_data_sharing_consent(self.test_user.username, self.retired_username)
        self._data_sharing_consent_assertions()

    def _data_sharing_consent_assertions(self):
        """
        Helper method for asserting that ``DataSharingConsent`` objects are retired.
        """
        self.consent.refresh_from_db()
        self.assertEqual(self.retired_username, self.consent.username)
        test_users_data_sharing_consent = DataSharingConsent.objects.filter(
            username=self.original_username
        )
        self.assertFalse(test_users_data_sharing_consent.exists())

    def test_can_retire_users_sap_success_factors_audits(self):
        AccountRetirementView.retire_sapsf_data_transmission(self.test_user)
        self._sapsf_audit_assertions()

    def _sapsf_audit_assertions(self):
        """
        Helper method for asserting that ``SapSuccessFactorsLearnerDataTransmissionAudit`` objects are retired.
        """
        self.sapsf_audit.refresh_from_db()
        self.assertEqual('', self.sapsf_audit.sapsf_user_id)
        audits_for_original_user_id = SapSuccessFactorsLearnerDataTransmissionAudit.objects.filter(
            sapsf_user_id=self.test_user.id,
        )
        self.assertFalse(audits_for_original_user_id.exists())

    def test_can_retire_user_from_pendingenterprisecustomeruser(self):
        AccountRetirementView.retire_user_from_pending_enterprise_customer_user(self.test_user, self.retired_email)
        self._pending_enterprise_customer_user_assertions()

    def _pending_enterprise_customer_user_assertions(self):
        """
        Helper method for asserting that ``PendingEnterpriseCustomerUser`` objects are retired.
        """
        self.pending_enterprise_user.refresh_from_db()
        self.assertEqual(self.retired_email, self.pending_enterprise_user.user_email)
        pending_enterprise_users = PendingEnterpriseCustomerUser.objects.filter(
            user_email=self.original_email
        )
        self.assertFalse(pending_enterprise_users.exists())

    def test_course_entitlement_support_detail_comments_are_retired(self):
        AccountRetirementView.retire_entitlement_support_detail(self.test_user)
        self._entitlement_support_detail_assertions()

    def _entitlement_support_detail_assertions(self):
        """
        Helper method for asserting that ``CourseEntitleSupportDetail`` objects are retired.
        """
        self.entitlement_support_detail.refresh_from_db()
        self.assertEqual('', self.entitlement_support_detail.comments)


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Account APIs are only supported in LMS')
class TestLMSAccountRetirementPost(RetirementTestCase, ModuleStoreTestCase):
    """
    Tests the LMS account retirement (GDPR P2) endpoint.
    """
    def setUp(self):
        super(TestLMSAccountRetirementPost, self).setUp()
        self.pii_standin = 'PII here'
        self.course = CourseFactory()
        self.test_user = UserFactory()
        self.test_superuser = SuperuserFactory()
        self.original_username = self.test_user.username
        self.original_email = self.test_user.email
        self.retired_username = get_retired_username_by_username(self.original_username)
        self.retired_email = get_retired_email_by_email(self.original_email)

        retirement_state = RetirementState.objects.get(state_name='RETIRING_LMS')
        self.retirement_status = UserRetirementStatus.create_retirement(self.test_user)
        self.retirement_status.current_state = retirement_state
        self.retirement_status.last_state = retirement_state
        self.retirement_status.save()

        # wiki data setup
        rp = RevisionPlugin.objects.create(article_id=0)
        RevisionPluginRevision.objects.create(
            revision_number=1,
            ip_address="ipaddresss",
            plugin=rp,
            user=self.test_user,
        )
        article = Article.objects.create()
        ArticleRevision.objects.create(ip_address="ipaddresss", user=self.test_user, article=article)

        # ManualEnrollmentAudit setup
        course_enrollment = CourseEnrollment.enroll(user=self.test_user, course_key=self.course.id)
        ManualEnrollmentAudit.objects.create(
            enrollment=course_enrollment, reason=self.pii_standin, enrolled_email=self.pii_standin
        )

        # CreditRequest and CreditRequirementStatus setup
        provider = CreditProvider.objects.create(provider_id="Hogwarts")
        credit_course = CreditCourse.objects.create(course_key=self.course.id)
        CreditRequest.objects.create(
            username=self.test_user.username,
            course=credit_course,
            provider_id=provider.id,
            parameters={self.pii_standin},
        )
        req = CreditRequirement.objects.create(course_id=credit_course.id)
        CreditRequirementStatus.objects.create(username=self.test_user.username, requirement=req)

        # ApiAccessRequest setup
        site = Site.objects.create()
        ApiAccessRequest.objects.create(
            user=self.test_user,
            site=site,
            website=self.pii_standin,
            company_address=self.pii_standin,
            company_name=self.pii_standin,
            reason=self.pii_standin,
        )

        # other setup
        PendingNameChange.objects.create(user=self.test_user, new_name=self.pii_standin, rationale=self.pii_standin)

        # setup for doing POST from test client
        self.headers = build_jwt_headers(self.test_superuser)
        self.headers['content_type'] = "application/json"
        self.url = reverse('accounts_retire_misc')

    def post_and_assert_status(self, data, expected_status=status.HTTP_204_NO_CONTENT):
        """
        Helper function for making a request to the retire subscriptions endpoint, and asserting the status.
        """
        response = self.client.post(self.url, json.dumps(data), **self.headers)
        self.assertEqual(response.status_code, expected_status)
        return response

    def test_retire_user(self):
        # check that rows that will not exist after retirement exist now
        self.assertTrue(CreditRequest.objects.filter(username=self.test_user.username).exists())
        self.assertTrue(CreditRequirementStatus.objects.filter(username=self.test_user.username).exists())
        self.assertTrue(PendingNameChange.objects.filter(user=self.test_user).exists())

        retirement = UserRetirementStatus.get_retirement_for_retirement_action(self.test_user.username)
        data = {'username': self.original_username}
        self.post_and_assert_status(data)

        self.test_user.refresh_from_db()
        self.test_user.profile.refresh_from_db()  # pylint: disable=no-member
        self.assertEqual(RevisionPluginRevision.objects.get(user=self.test_user).ip_address, None)
        self.assertEqual(ArticleRevision.objects.get(user=self.test_user).ip_address, None)
        self.assertFalse(PendingNameChange.objects.filter(user=self.test_user).exists())

        self.assertEqual(
            ManualEnrollmentAudit.objects.get(
                enrollment=CourseEnrollment.objects.get(user=self.test_user)
            ).enrolled_email,
            retirement.retired_email
        )
        self.assertFalse(CreditRequest.objects.filter(username=self.test_user.username).exists())
        self.assertTrue(CreditRequest.objects.filter(username=retirement.retired_username).exists())
        self.assertEqual(CreditRequest.objects.get(username=retirement.retired_username).parameters, {})

        self.assertFalse(CreditRequirementStatus.objects.filter(username=self.test_user.username).exists())
        self.assertTrue(CreditRequirementStatus.objects.filter(username=retirement.retired_username).exists())
        self.assertEqual(CreditRequirementStatus.objects.get(username=retirement.retired_username).reason, {})

        retired_api_access_request = ApiAccessRequest.objects.get(user=self.test_user)
        self.assertEqual(retired_api_access_request.website, '')
        self.assertEqual(retired_api_access_request.company_address, '')
        self.assertEqual(retired_api_access_request.company_name, '')
        self.assertEqual(retired_api_access_request.reason, '')

    def test_retire_user_twice_idempotent(self):
        # check that a second call to the retire_misc endpoint will work
        data = {'username': self.original_username}
        self.post_and_assert_status(data)
        fake_completed_retirement(self.test_user)
        self.post_and_assert_status(data)
