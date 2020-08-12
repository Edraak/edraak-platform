"""
Test the partitions and partitions service

"""

from datetime import datetime
from django.test import TestCase
from mock import Mock, patch

from opaque_keys.edx.locator import CourseLocator
from stevedore.extension import Extension, ExtensionManager
from xmodule.partitions.partitions import (
    Group, UserPartition, UserPartitionError, NoSuchUserPartitionGroupError,
    USER_PARTITION_SCHEME_NAMESPACE, ENROLLMENT_TRACK_PARTITION_ID
)
from xmodule.partitions.partitions_service import (
    PartitionService, get_all_partitions_for_course, FEATURES
)
from openedx.features.content_type_gating.models import ContentTypeGatingConfig


class TestGroup(TestCase):
    """Test constructing groups"""
    shard = 2

    def test_construct(self):
        test_id = 10
        name = "Grendel"
        group = Group(test_id, name)
        self.assertEqual(group.id, test_id)
        self.assertEqual(group.name, name)

    def test_string_id(self):
        test_id = "10"
        name = "Grendel"
        group = Group(test_id, name)
        self.assertEqual(group.id, 10)

    def test_to_json(self):
        test_id = 10
        name = "Grendel"
        group = Group(test_id, name)
        jsonified = group.to_json()
        act_jsonified = {
            "id": test_id,
            "name": name,
            "version": group.VERSION
        }
        self.assertEqual(jsonified, act_jsonified)

    def test_from_json(self):
        test_id = 5
        name = "Grendel"
        jsonified = {
            "id": test_id,
            "name": name,
            "version": Group.VERSION
        }
        group = Group.from_json(jsonified)
        self.assertEqual(group.id, test_id)
        self.assertEqual(group.name, name)

    def test_from_json_broken(self):
        test_id = 5
        name = "Grendel"
        # Bad version
        jsonified = {
            "id": test_id,
            "name": name,
            "version": -1,
        }
        with self.assertRaisesRegexp(TypeError, "has unexpected version"):
            Group.from_json(jsonified)

        # Missing key "id"
        jsonified = {
            "name": name,
            "version": Group.VERSION
        }
        with self.assertRaisesRegexp(TypeError, "missing value key 'id'"):
            Group.from_json(jsonified)

        # Has extra key - should not be a problem
        jsonified = {
            "id": test_id,
            "name": name,
            "version": Group.VERSION,
            "programmer": "Cale"
        }
        group = Group.from_json(jsonified)
        self.assertNotIn("programmer", group.to_json())


class MockUserPartitionScheme(object):
    """
    Mock user partition scheme
    """
    def __init__(self, name="mock", current_group=None, **kwargs):
        super(MockUserPartitionScheme, self).__init__(**kwargs)
        self.name = name
        self.current_group = current_group

    def get_group_for_user(self, course_id, user, user_partition, assign=True):  # pylint: disable=unused-argument
        """
        Returns the current group if set, else the first group from the specified user partition.
        """
        if self.current_group:
            return self.current_group
        groups = user_partition.groups
        if not groups or len(groups) == 0:
            return None
        return groups[0]


class MockEnrollmentTrackUserPartitionScheme(MockUserPartitionScheme):

    def create_user_partition(self, id, name, description, groups=None, parameters=None, active=True):  # pylint: disable=redefined-builtin, invalid-name, unused-argument
        """
        The EnrollmentTrackPartitionScheme provides this method to return a subclass of UserPartition.
        """
        return UserPartition(id, name, description, groups, self, parameters, active)


class PartitionTestCase(TestCase):
    """Base class for test cases that require partitions"""
    shard = 2
    TEST_ID = 0
    TEST_NAME = "Mock Partition"
    TEST_DESCRIPTION = "for testing purposes"
    TEST_PARAMETERS = {"location": "block-v1:edX+DemoX+Demo+type@block@uuid"}
    TEST_GROUPS = [Group(0, 'Group 1'), Group(1, 'Group 2')]
    TEST_SCHEME_NAME = "mock"
    ENROLLMENT_TRACK_SCHEME_NAME = "enrollment_track"

    def setUp(self):
        super(PartitionTestCase, self).setUp()
        # Set up two user partition schemes: mock and random
        self.non_random_scheme = MockUserPartitionScheme(self.TEST_SCHEME_NAME)
        self.random_scheme = MockUserPartitionScheme("random")
        self.enrollment_track_scheme = MockEnrollmentTrackUserPartitionScheme(self.ENROLLMENT_TRACK_SCHEME_NAME)
        extensions = [
            Extension(
                self.non_random_scheme.name, USER_PARTITION_SCHEME_NAMESPACE, self.non_random_scheme, None
            ),
            Extension(
                self.random_scheme.name, USER_PARTITION_SCHEME_NAMESPACE, self.random_scheme, None
            ),
            Extension(
                self.enrollment_track_scheme.name, USER_PARTITION_SCHEME_NAMESPACE, self.enrollment_track_scheme, None
            ),
        ]
        UserPartition.scheme_extensions = ExtensionManager.make_test_instance(
            extensions, namespace=USER_PARTITION_SCHEME_NAMESPACE
        )

        # Be sure to clean up the global scheme_extensions after the test.
        self.addCleanup(self.cleanup_scheme_extensions)

        # Create a test partition
        self.user_partition = UserPartition(
            self.TEST_ID,
            self.TEST_NAME,
            self.TEST_DESCRIPTION,
            self.TEST_GROUPS,
            extensions[0].plugin,
            self.TEST_PARAMETERS,
        )

        # Make sure the names are set on the schemes (which happens normally in code, but may not happen in tests).
        self.user_partition.get_scheme(self.non_random_scheme.name)
        self.user_partition.get_scheme(self.random_scheme.name)

    def cleanup_scheme_extensions(self):
        """
        Unset the UserPartition.scheme_extensions cache.
        """
        UserPartition.scheme_extensions = None


class TestUserPartition(PartitionTestCase):
    """Test constructing UserPartitions"""
    shard = 2

    def test_construct(self):
        user_partition = UserPartition(
            self.TEST_ID,
            self.TEST_NAME,
            self.TEST_DESCRIPTION,
            self.TEST_GROUPS,
            MockUserPartitionScheme(),
            self.TEST_PARAMETERS,
        )
        self.assertEqual(user_partition.id, self.TEST_ID)
        self.assertEqual(user_partition.name, self.TEST_NAME)
        self.assertEqual(user_partition.description, self.TEST_DESCRIPTION)
        self.assertEqual(user_partition.groups, self.TEST_GROUPS)
        self.assertEquals(user_partition.scheme.name, self.TEST_SCHEME_NAME)
        self.assertEquals(user_partition.parameters, self.TEST_PARAMETERS)

    def test_string_id(self):
        user_partition = UserPartition(
            "70",
            self.TEST_NAME,
            self.TEST_DESCRIPTION,
            self.TEST_GROUPS,
            MockUserPartitionScheme(),
            self.TEST_PARAMETERS,
        )
        self.assertEqual(user_partition.id, 70)

    def test_to_json(self):
        jsonified = self.user_partition.to_json()
        act_jsonified = {
            "id": self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": self.user_partition.VERSION,
            "scheme": self.TEST_SCHEME_NAME,
            "active": True,
        }
        self.assertEqual(jsonified, act_jsonified)

    def test_from_json(self):
        jsonified = {
            "id": self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": UserPartition.VERSION,
            "scheme": "mock",
        }
        user_partition = UserPartition.from_json(jsonified)
        self.assertEqual(user_partition.id, self.TEST_ID)
        self.assertEqual(user_partition.name, self.TEST_NAME)
        self.assertEqual(user_partition.description, self.TEST_DESCRIPTION)
        self.assertEqual(user_partition.parameters, self.TEST_PARAMETERS)

        for act_group in user_partition.groups:
            self.assertIn(act_group.id, [0, 1])
            exp_group = self.TEST_GROUPS[act_group.id]
            self.assertEqual(exp_group.id, act_group.id)
            self.assertEqual(exp_group.name, act_group.name)

    def test_version_upgrade(self):
        # Test that version 1 partitions did not have a scheme specified
        # and have empty parameters
        jsonified = {
            "id": self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": 1,
        }
        user_partition = UserPartition.from_json(jsonified)
        self.assertEqual(user_partition.scheme.name, "random")
        self.assertEqual(user_partition.parameters, {})
        self.assertTrue(user_partition.active)

    def test_version_upgrade_2_to_3(self):
        # Test that version 3 user partition raises error if 'scheme' field is
        # not provided (same behavior as version 2)
        jsonified = {
            'id': self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": 2,
        }
        with self.assertRaisesRegexp(TypeError, "missing value key 'scheme'"):
            UserPartition.from_json(jsonified)

        # Test that version 3 partitions have a scheme specified
        # and a field 'parameters' (optional while setting user partition but
        # always present in response)
        jsonified = {
            "id": self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": 2,
            "scheme": self.TEST_SCHEME_NAME,
        }
        user_partition = UserPartition.from_json(jsonified)
        self.assertEqual(user_partition.scheme.name, self.TEST_SCHEME_NAME)
        self.assertEqual(user_partition.parameters, {})
        self.assertTrue(user_partition.active)

        # now test that parameters dict is present in response with same value
        # as provided
        jsonified = {
            "id": self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "parameters": self.TEST_PARAMETERS,
            "version": 3,
            "scheme": self.TEST_SCHEME_NAME,
        }
        user_partition = UserPartition.from_json(jsonified)
        self.assertEqual(user_partition.parameters, self.TEST_PARAMETERS)
        self.assertTrue(user_partition.active)

    def test_from_json_broken(self):
        # Missing field
        jsonified = {
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": UserPartition.VERSION,
            "scheme": self.TEST_SCHEME_NAME,
        }
        with self.assertRaisesRegexp(TypeError, "missing value key 'id'"):
            UserPartition.from_json(jsonified)

        # Missing scheme
        jsonified = {
            'id': self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": UserPartition.VERSION,
        }
        with self.assertRaisesRegexp(TypeError, "missing value key 'scheme'"):
            UserPartition.from_json(jsonified)

        # Invalid scheme
        jsonified = {
            'id': self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": UserPartition.VERSION,
            "scheme": "no_such_scheme",
        }
        with self.assertRaisesRegexp(UserPartitionError, "Unrecognized scheme"):
            UserPartition.from_json(jsonified)

        # Wrong version
        jsonified = {
            'id': self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": -1,
            "scheme": self.TEST_SCHEME_NAME,
        }
        with self.assertRaisesRegexp(TypeError, "has unexpected version"):
            UserPartition.from_json(jsonified)

        # Has extra key - should not be a problem
        jsonified = {
            'id': self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "parameters": self.TEST_PARAMETERS,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": UserPartition.VERSION,
            "scheme": "mock",
            "programmer": "Cale",
        }
        user_partition = UserPartition.from_json(jsonified)
        self.assertNotIn("programmer", user_partition.to_json())

        # No error on missing parameters key (which is optional)
        jsonified = {
            'id': self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": UserPartition.VERSION,
            "scheme": "mock",
        }
        user_partition = UserPartition.from_json(jsonified)
        self.assertEqual(user_partition.parameters, {})

    def test_get_group(self):
        """
        UserPartition.get_group correctly returns the group referenced by the
        `group_id` parameter, or raises NoSuchUserPartitionGroupError when
        the lookup fails.
        """
        self.assertEqual(
            self.user_partition.get_group(self.TEST_GROUPS[0].id),
            self.TEST_GROUPS[0]
        )
        self.assertEqual(
            self.user_partition.get_group(self.TEST_GROUPS[1].id),
            self.TEST_GROUPS[1]
        )
        with self.assertRaises(NoSuchUserPartitionGroupError):
            self.user_partition.get_group(3)

    def test_forward_compatibility(self):
        # If the user partition version is updated in a release,
        # then the release is rolled back, courses might contain
        # version numbers greater than the currently deployed
        # version number.
        newer_version_json = {
            "id": self.TEST_ID,
            "name": self.TEST_NAME,
            "description": self.TEST_DESCRIPTION,
            "groups": [group.to_json() for group in self.TEST_GROUPS],
            "version": UserPartition.VERSION + 1,
            "scheme": "mock",
            "additional_new_field": "foo",
        }
        partition = UserPartition.from_json(newer_version_json)
        self.assertEqual(partition.id, self.TEST_ID)
        self.assertEqual(partition.name, self.TEST_NAME)


class MockPartitionService(PartitionService):
    """
    Mock PartitionService for testing.
    """
    def __init__(self, course, **kwargs):
        super(MockPartitionService, self).__init__(**kwargs)
        self._course = course

    def get_course(self):
        return self._course


class PartitionServiceBaseClass(PartitionTestCase):
    """
    Base test class for testing the PartitionService.
    """

    def setUp(self):
        super(PartitionServiceBaseClass, self).setUp()

        ContentTypeGatingConfig.objects.create(
            enabled=True,
            enabled_as_of=datetime(2018, 1, 1),
            studio_override_enabled=True
        )
        self.course = Mock(id=CourseLocator('org_0', 'course_0', 'run_0'))
        self.partition_service = self._create_service("ma")

    def _create_service(self, username, cache=None):
        """Convenience method to generate a MockPartitionService for a user."""
        # Derive a "user_id" from the username, just so we don't have to add an
        # extra param to this method. Just has to be unique per user.
        user_id = abs(hash(username))
        self.user = Mock(
            username=username, email='{}@edx.org'.format(username), is_staff=False, is_active=True, id=user_id
        )
        self.course.user_partitions = [self.user_partition]

        return MockPartitionService(
            self.course,
            course_id=self.course.id,
            cache=cache
        )


class TestPartitionService(PartitionServiceBaseClass):
    """
    Test getting a user's group out of a partition
    """
    shard = 2

    def test_get_user_group_id_for_partition(self):
        # assign the first group to be returned
        user_partition_id = self.user_partition.id
        groups = self.user_partition.groups
        self.user_partition.scheme.current_group = groups[0]

        # get a group assigned to the user
        group1_id = self.partition_service.get_user_group_id_for_partition(self.user, user_partition_id)
        assert group1_id == groups[0].id

        # switch to the second group and verify that it is returned for the user
        self.user_partition.scheme.current_group = groups[1]
        group2_id = self.partition_service.get_user_group_id_for_partition(self.user, user_partition_id)
        assert group2_id == groups[1].id

    def test_caching(self):
        username = "psvc_cache_user"
        user_partition_id = self.user_partition.id
        shared_cache = {}

        # Two MockPartitionService objects that share the same cache:
        ps_shared_cache_1 = self._create_service(username, shared_cache)
        ps_shared_cache_2 = self._create_service(username, shared_cache)

        # A MockPartitionService with its own local cache
        ps_diff_cache = self._create_service(username, {})

        # A MockPartitionService that never uses caching.
        ps_uncached = self._create_service(username)

        # Set the group we expect users to be placed into
        first_group = self.user_partition.groups[0]
        self.user_partition.scheme.current_group = first_group

        # Make sure our partition services all return the right thing, but skip
        # ps_shared_cache_2 so we can see if its cache got updated anyway.
        for part_svc in [ps_shared_cache_1, ps_diff_cache, ps_uncached]:
            self.assertEqual(
                first_group.id,
                part_svc.get_user_group_id_for_partition(self.user, user_partition_id)
            )

        # Now select a new target group
        second_group = self.user_partition.groups[1]
        self.user_partition.scheme.current_group = second_group

        # Both of the shared cache entries should return the old value, even
        # ps_shared_cache_2, which was never asked for the value the first time
        # Likewise, our separately cached piece should return the original answer
        for part_svc in [ps_shared_cache_1, ps_shared_cache_2, ps_diff_cache]:
            self.assertEqual(
                first_group.id,
                part_svc.get_user_group_id_for_partition(self.user, user_partition_id)
            )

        # Our uncached service should be accurate.
        self.assertEqual(
            second_group.id,
            ps_uncached.get_user_group_id_for_partition(self.user, user_partition_id)
        )

        # And a newly created service should see the right thing
        ps_new_cache = self._create_service(username, {})
        self.assertEqual(
            second_group.id,
            ps_new_cache.get_user_group_id_for_partition(self.user, user_partition_id)
        )

    def test_get_group(self):
        """
        Test that a partition group is assigned to a user.
        """
        groups = self.user_partition.groups

        # assign first group and verify that it is returned for the user
        self.user_partition.scheme.current_group = groups[0]
        group1 = self.partition_service.get_group(self.user, self.user_partition)
        self.assertEqual(group1, groups[0])

        # switch to the second group and verify that it is returned for the user
        self.user_partition.scheme.current_group = groups[1]
        group2 = self.partition_service.get_group(self.user, self.user_partition)
        self.assertEqual(group2, groups[1])


class TestGetCourseUserPartitions(PartitionServiceBaseClass):
    """
    Test the helper method get_all_partitions_for_course.
    """
    shard = 2

    def setUp(self):
        super(TestGetCourseUserPartitions, self).setUp()
        TestGetCourseUserPartitions._enable_enrollment_track_partition(True)

    @staticmethod
    def _enable_enrollment_track_partition(enable):
        """
        Enable or disable the feature flag for the enrollment track user partition.
        """
        FEATURES['ENABLE_ENROLLMENT_TRACK_USER_PARTITION'] = enable

    def test_enrollment_track_partition_added(self):
        """
        Test that the dynamic enrollment track scheme is added if there is no conflict with the user partition ID.
        """
        all_partitions = get_all_partitions_for_course(self.course)
        self.assertEqual(2, len(all_partitions))
        self.assertEqual(self.TEST_SCHEME_NAME, all_partitions[0].scheme.name)
        enrollment_track_partition = all_partitions[1]
        self.assertEqual(self.ENROLLMENT_TRACK_SCHEME_NAME, enrollment_track_partition.scheme.name)
        self.assertEqual(unicode(self.course.id), enrollment_track_partition.parameters['course_id'])
        self.assertEqual(ENROLLMENT_TRACK_PARTITION_ID, enrollment_track_partition.id)

    def test_enrollment_track_partition_not_added_if_conflict(self):
        """
        Test that the dynamic enrollment track scheme is NOT added if a UserPartition exists with that ID.
        """
        self.user_partition = UserPartition(
            ENROLLMENT_TRACK_PARTITION_ID,
            self.TEST_NAME,
            self.TEST_DESCRIPTION,
            self.TEST_GROUPS,
            self.non_random_scheme,
            self.TEST_PARAMETERS,
        )
        self.course.user_partitions = [self.user_partition]
        all_partitions = get_all_partitions_for_course(self.course)
        self.assertEqual(1, len(all_partitions))
        self.assertEqual(self.TEST_SCHEME_NAME, all_partitions[0].scheme.name)

    def test_enrollment_track_partition_not_added_if_disabled(self):
        """
        Test that the dynamic enrollment track scheme is NOT added if the settings FEATURE flag is disabled.
        """
        TestGetCourseUserPartitions._enable_enrollment_track_partition(False)
        all_partitions = get_all_partitions_for_course(self.course)
        self.assertEqual(1, len(all_partitions))
        self.assertEqual(self.TEST_SCHEME_NAME, all_partitions[0].scheme.name)

    def test_filter_inactive_user_partitions(self):
        """
        Tests supplying the `active_only` parameter.
        """
        self.user_partition = UserPartition(
            self.TEST_ID,
            self.TEST_NAME,
            self.TEST_DESCRIPTION,
            self.TEST_GROUPS,
            self.non_random_scheme,
            self.TEST_PARAMETERS,
            active=False
        )
        self.course.user_partitions = [self.user_partition]

        all_partitions = get_all_partitions_for_course(self.course, active_only=True)
        self.assertEqual(1, len(all_partitions))
        self.assertEqual(self.ENROLLMENT_TRACK_SCHEME_NAME, all_partitions[0].scheme.name)

        all_partitions = get_all_partitions_for_course(self.course, active_only=False)
        self.assertEqual(2, len(all_partitions))
        self.assertEqual(self.TEST_SCHEME_NAME, all_partitions[0].scheme.name)
        self.assertEqual(self.ENROLLMENT_TRACK_SCHEME_NAME, all_partitions[1].scheme.name)
