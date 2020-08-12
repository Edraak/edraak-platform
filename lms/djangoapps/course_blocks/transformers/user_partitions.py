"""
User Partitions Transformer
"""
from lms.djangoapps.courseware.access import has_access
from openedx.core.djangoapps.content.block_structure.transformer import (
    BlockStructureTransformer,
    FilteringTransformerMixin
)
from xmodule.partitions.partitions_service import get_user_partition_groups, get_all_partitions_for_course

from .split_test import SplitTestTransformer
from .utils import get_field_on_block


class UserPartitionTransformer(FilteringTransformerMixin, BlockStructureTransformer):
    """
    A transformer that enforces the group access rules on course blocks,
    by honoring their user_partitions and group_access fields, and
    removing all blocks in the block structure to which the user does
    not have group access.

    Staff users are *not* exempted from user partition pathways.
    """
    WRITE_VERSION = 1
    READ_VERSION = 1

    @classmethod
    def name(cls):
        """
        Unique identifier for the transformer's class;
        same identifier used in setup.py.
        """
        return "user_partitions"

    @classmethod
    def collect(cls, block_structure):
        """
        Computes any information for each XBlock that's necessary to
        execute this transformer's transform method.

        Arguments:
            block_structure (BlockStructureCollectedData)
        """
        # First have the split test transformer setup its group access
        # data for each block.
        SplitTestTransformer.collect(block_structure)

        # Because user partitions are course-wide, only store data for
        # them on the root block.
        root_block = block_structure.get_xblock(block_structure.root_block_usage_key)
        user_partitions = get_all_partitions_for_course(root_block, active_only=True)
        block_structure.set_transformer_data(cls, 'user_partitions', user_partitions)

        # If there are no user partitions, this transformation is a
        # no-op, so there is nothing to collect.
        if not user_partitions:
            return

        # For each block, compute merged group access. Because this is a
        # topological sort, we know a block's parents are guaranteed to
        # already have merged group access computed before the block
        # itself.
        for block_key in block_structure.topological_traversal():
            xblock = block_structure.get_xblock(block_key)
            parent_keys = block_structure.get_parents(block_key)
            merged_parent_access_list = [
                block_structure.get_transformer_block_field(parent_key, cls, 'merged_group_access')
                for parent_key in parent_keys
            ]
            merged_group_access = _MergedGroupAccess(user_partitions, xblock, merged_parent_access_list)
            block_structure.set_transformer_block_field(block_key, cls, 'merged_group_access', merged_group_access)

    def transform_block_filters(self, usage_info, block_structure):
        user = usage_info.user
        result_list = SplitTestTransformer().transform_block_filters(usage_info, block_structure)

        user_partitions = block_structure.get_transformer_data(self, 'user_partitions')
        if not user_partitions:
            return [block_structure.create_universal_filter()]

        user_groups = get_user_partition_groups(usage_info.course_key, user_partitions, user, 'id')
        group_access_filter = block_structure.create_removal_filter(
            lambda block_key: not (
                has_access(user, 'staff', block_key) or
                block_structure.get_transformer_block_field(block_key, self, 'merged_group_access').check_group_access(
                    user_groups
                )
            )
        )

        result_list.append(group_access_filter)
        return result_list


class _MergedGroupAccess(object):
    """
    A class object to represent the computed access value for a block,
    merged from the inherited values from its ancestors.

    Note: The implementation assumes that the block structure is
    topologically traversed so that all parents' merged accesses are
    computed before a block's.

    How group access restrictions are represented within an XBlock:
      - group_access not defined
                    => No group access restrictions.
      - For each partition:
          - partition.id not in group_access
                    => All groups have access for this partition
          - group_access[partition_id] is None
                    => All groups have access for this partition
          - group_access[partition_id] == []
                    => All groups have access for this partition
          - group_access[partition_id] == [group1..groupN]
                    => groups 1..N have access for this partition

    We internally represent the restrictions in a simplified way:
      - self._access == {}
                    => No group access restrictions.
      - For each partition:
          - partition.id not in _access
                    => All groups have access for this partition
          - _access[partition_id] == set()
                    => No groups have access for this partition
          - _access[partition_id] == set(group1..groupN)
                    => groups 1..N have access for this partition

    Note that a user must have access to all partitions in group_access
    or _access in order to access a block.
    """
    def __init__(self, user_partitions, xblock, merged_parent_access_list):
        """
        Arguments:
            user_partitions (list[UserPartition])
            xblock (XBlock)
            merged_parent_access_list (list[_MergedGroupAccess])
        """

        # { partition.id: set(IDs of groups that can access partition) }
        # If partition id is absent in this dict, no group access
        # restrictions exist for that partition.
        self._access = {}

        # Get the group_access value that is directly set on the xblock.
        # Do not get the inherited value since field inheritance doesn't
        # take a union of them for DAGs.
        xblock_group_access = get_field_on_block(xblock, 'group_access', default_value={})

        for partition in user_partitions:
            # Running list of all groups that have access to this
            # block, computed as a "union" from all parent chains.
            #
            # Set the default to universal access, for the case when
            # there are no parents.
            merged_parent_group_ids = None

            if merged_parent_access_list:
                # Set the default to most restrictive as we iterate
                # through all the parent chains.
                merged_parent_group_ids = set()

                # Loop through parent_access from each parent-chain
                for merged_parent_access in merged_parent_access_list:
                    # pylint: disable=protected-access
                    if partition.id in merged_parent_access._access:
                        # Since this parent has group access
                        # restrictions, merge it with the running list
                        # of parent-introduced restrictions.
                        merged_parent_group_ids.update(merged_parent_access._access[partition.id])
                    else:
                        # Since this parent chain has no group access
                        # restrictions for this partition, allow
                        # unfettered group access for this partition
                        # and don't bother checking the rest of the
                        # parents.
                        merged_parent_group_ids = None
                        break

            # Group access for this partition as stored on the xblock
            xblock_partition_access = set(xblock_group_access.get(partition.id) or []) or None

            # Compute this block's access by intersecting the block's
            # own access with the merged access from its parent chains.
            merged_group_ids = _MergedGroupAccess._intersection(xblock_partition_access, merged_parent_group_ids)

            # Add this partition's access only if group restrictions
            # exist.
            if merged_group_ids is not None:
                self._access[partition.id] = merged_group_ids

    @staticmethod
    def _intersection(*sets):
        """
        Compute an intersection of sets, interpreting None as the
        Universe set.

        This makes __init__ a bit more elegant.

        Arguments:
            sets (list[set or None]), where None represents the Universe
            set.

        Returns:
            set or None, where None represents the Universe set.
        """
        non_universe_sets = [set_ for set_ in sets if set_ is not None]
        if non_universe_sets:
            first, rest = non_universe_sets[0], non_universe_sets[1:]
            return first.intersection(*rest)
        else:
            return None

    def check_group_access(self, user_groups):
        """
        Arguments:
            dict[int: Group]: Given a user, a mapping from user
                partition IDs to the group to which the user belongs in
                each partition.

        Returns:
            bool: Whether said user has group access.
        """
        for partition_id, allowed_group_ids in self._access.iteritems():

            # If the user is not assigned to a group for this partition,
            # deny access.
            if partition_id not in user_groups:
                return False

            # If the user belongs to one of the allowed groups for this
            # partition, then move and check the next partition.
            elif user_groups[partition_id].id in allowed_group_ids:
                continue

            # Else, deny access.
            else:
                return False

        # The user has access for every partition, grant access.
        return True
