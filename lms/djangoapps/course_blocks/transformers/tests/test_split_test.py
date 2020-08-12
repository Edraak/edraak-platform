"""
Tests for SplitTestTransformer.
"""
import ddt

import openedx.core.djangoapps.user_api.course_tag.api as course_tag_api
from openedx.core.djangoapps.user_api.partition_schemes import RandomUserPartitionScheme
from student.tests.factories import CourseEnrollmentFactory
from xmodule.modulestore.tests.factories import check_mongo_calls
from xmodule.partitions.partitions import Group, UserPartition
from xmodule.partitions.partitions_service import get_user_partition_groups

from ...api import get_course_blocks
from ..user_partitions import UserPartitionTransformer
from .helpers import CourseStructureTestCase, create_location


@ddt.ddt
class SplitTestTransformerTestCase(CourseStructureTestCase):
    """
    SplitTestTransformer Test
    """
    TEST_PARTITION_ID = 0
    TRANSFORMER_CLASS_TO_TEST = UserPartitionTransformer
    shard = 3

    def setUp(self):
        """
        Setup course structure and create user for split test transformer test.
        """
        super(SplitTestTransformerTestCase, self).setUp()

        # Set up user partitions and groups.
        self.groups = [Group(0, 'Group 0'), Group(1, 'Group 1'), Group(2, 'Group 2')]
        self.split_test_user_partition_id = self.TEST_PARTITION_ID
        self.split_test_user_partition = UserPartition(
            id=self.split_test_user_partition_id,
            name='Split Partition',
            description='This is split partition',
            groups=self.groups,
            scheme=RandomUserPartitionScheme
        )
        self.split_test_user_partition.scheme.name = "random"

        # Build course.
        self.course_hierarchy = self.get_course_hierarchy()
        self.blocks = self.build_course(self.course_hierarchy)
        self.course = self.blocks['course']

        # Enroll user in course.
        CourseEnrollmentFactory.create(user=self.user, course_id=self.course.id, is_active=True)

    def get_course_hierarchy(self):
        """
        Get a course hierarchy to test with.

        Assumes self.split_test_user_partition has already been initialized.

        Returns: dict[course_structure]
        """

        org_name = 'SplitTestTransformer'
        course_name = 'ST101F'
        run_name = 'test_run'

        def location(block_ref, block_type='vertical'):
            """
            Returns the usage key for the given block_type and block reference string in the test course.
            """
            return create_location(
                org_name, course_name, run_name, block_type, self.create_block_id(block_type, block_ref)
            )

        #                 course
        #              /    |        \
        #             /     |         \
        #           A     BSplit        CSplit
        #          / \   /  |   \         |   \
        #         /   \ /   |    \        |    \
        #        D     E[1] F[2] G[3]    H[1]  I[2]
        #                    / \    \      |
        #                   /   \    \     |
        #                  J  KSplit  \    L
        #                     /  |    \   / \
        #                    /   |    \  /   \
        #                  M[2] N[3]   O     P
        #
        return [
            {
                'org': org_name,
                'course': course_name,
                'run': run_name,
                'user_partitions': [self.split_test_user_partition],
                '#type': 'course',
                '#ref': 'course',
            },
            {
                '#type': 'vertical',
                '#ref': 'A',
                '#children': [{'#type': 'vertical', '#ref': 'D'}],
            },
            {
                '#type': 'split_test',
                '#ref': 'BSplit',
                'metadata': {'category': 'split_test'},
                'user_partition_id': self.TEST_PARTITION_ID,
                'group_id_to_child': {
                    '0': location('E'),
                    '1': location('F'),
                    '2': location('G'),
                },
                '#children': [{'#type': 'vertical', '#ref': 'G'}],
            },
            {
                '#type': 'vertical',
                '#ref': 'E',
                '#parents': ['A', 'BSplit'],
            },
            {
                '#type': 'vertical',
                '#ref': 'F',
                '#parents': ['BSplit'],
                '#children': [
                    {'#type': 'vertical', '#ref': 'J'},
                ],
            },
            {
                '#type': 'split_test',
                '#ref': 'KSplit',
                'metadata': {'category': 'split_test'},
                'user_partition_id': self.TEST_PARTITION_ID,
                'group_id_to_child': {
                    '1': location('M'),
                    '2': location('N'),
                },
                '#parents': ['F'],
                '#children': [
                    {'#type': 'vertical', '#ref': 'M'},
                    {'#type': 'vertical', '#ref': 'N'},
                ],
            },
            {
                '#type': 'split_test',
                '#ref': 'CSplit',
                'metadata': {'category': 'split_test'},
                'user_partition_id': self.TEST_PARTITION_ID,
                'group_id_to_child': {
                    '0': location('H'),
                    '1': location('I'),
                },
                '#children': [
                    {'#type': 'vertical', '#ref': 'I'},
                    {
                        '#type': 'vertical',
                        '#ref': 'H',
                        '#children': [
                            {
                                '#type': 'vertical',
                                '#ref': 'L',
                                '#children': [{'#type': 'vertical', '#ref': 'P'}],
                            },
                        ],
                    },
                ],
            },
            {
                '#type': 'vertical',
                '#ref': 'O',
                '#parents': ['G', 'L'],
            },
        ]

    @ddt.data(
        # Note: Theoretically, block E should be accessible by users
        #  not in Group 0, since there's an open path through block A.
        #  Since the split_test transformer automatically sets the block
        #  access on its children, it bypasses the paths via other
        #  parents. However, we don't think this is a use case we need to
        #  support for split_test components (since they are now deprecated
        #  in favor of content groups and user partitions).
        (0, ('course', 'A', 'D', 'E', 'H', 'L', 'O', 'P',)),
        (1, ('course', 'A', 'D', 'F', 'J', 'M', 'I',)),
        (2, ('course', 'A', 'D', 'G', 'O',)),
    )
    @ddt.unpack
    def test_user(self, group_id, expected_blocks):
        course_tag_api.set_course_tag(
            self.user,
            self.course.id,
            RandomUserPartitionScheme.key_for_partition(self.split_test_user_partition),
            group_id,
        )

        block_structure1 = get_course_blocks(
            self.user,
            self.course.location,
            self.transformers,
        )
        self.assertEqual(
            set(block_structure1.get_block_keys()),
            set(self.get_block_key_set(self.blocks, *expected_blocks)),
        )

    def test_user_randomly_assigned(self):
        # user was randomly assigned to one of the groups
        user_groups = get_user_partition_groups(
            self.course.id, [self.split_test_user_partition], self.user, 'id'
        )
        self.assertEquals(len(user_groups), 1)

        # calling twice should result in the same block set
        block_structure1 = get_course_blocks(
            self.user,
            self.course.location,
            self.transformers,
        )
        with check_mongo_calls(0):
            block_structure2 = get_course_blocks(
                self.user,
                self.course.location,
                self.transformers,
            )
        self.assertEqual(
            set(block_structure1.get_block_keys()),
            set(block_structure2.get_block_keys()),
        )
