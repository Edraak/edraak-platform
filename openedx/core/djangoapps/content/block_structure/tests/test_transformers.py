"""
Tests for transformers.py
"""
from mock import MagicMock, patch
from unittest import TestCase

from ..block_structure import BlockStructureModulestoreData
from ..exceptions import TransformerException, TransformerDataIncompatible
from ..transformers import BlockStructureTransformers
from .helpers import (
    ChildrenMapTestMixin, MockTransformer, MockFilteringTransformer, mock_registered_transformers
)


class TestBlockStructureTransformers(ChildrenMapTestMixin, TestCase):
    """
    Test class for testing BlockStructureTransformers
    """
    shard = 2

    class UnregisteredTransformer(MockTransformer):
        """
        Mock transformer that is not registered.
        """
        pass

    def setUp(self):
        super(TestBlockStructureTransformers, self).setUp()
        self.transformers = BlockStructureTransformers(usage_info=MagicMock())
        self.registered_transformers = [MockTransformer(), MockFilteringTransformer()]

    def add_mock_transformer(self):
        """
        Adds the registered transformers to the self.transformers collection.
        """
        with mock_registered_transformers(self.registered_transformers):
            self.transformers += self.registered_transformers

    def test_add_registered(self):
        self.add_mock_transformer()
        self.assertIn(
            self.registered_transformers[0],
            self.transformers._transformers['no_filter']  # pylint: disable=protected-access
        )
        self.assertIn(
            self.registered_transformers[1],
            self.transformers._transformers['supports_filter']  # pylint: disable=protected-access
        )

    def test_add_unregistered(self):
        with self.assertRaises(TransformerException):
            self.transformers += [self.UnregisteredTransformer()]

        self.assertEquals(self.transformers._transformers['no_filter'], [])  # pylint: disable=protected-access
        self.assertEquals(self.transformers._transformers['supports_filter'], [])  # pylint: disable=protected-access

    def test_collect(self):
        with mock_registered_transformers(self.registered_transformers):
            with patch(
                'openedx.core.djangoapps.content.block_structure.tests.helpers.MockTransformer.collect'
            ) as mock_collect_call:
                BlockStructureTransformers.collect(block_structure=MagicMock())
                self.assertTrue(mock_collect_call.called)

    def test_transform(self):
        self.add_mock_transformer()

        with patch(
            'openedx.core.djangoapps.content.block_structure.tests.helpers.MockTransformer.transform'
        ) as mock_transform_call:
            self.transformers.transform(block_structure=MagicMock())
            self.assertTrue(mock_transform_call.called)

    def test_verify_versions(self):
        block_structure = self.create_block_structure(
            self.SIMPLE_CHILDREN_MAP,
            BlockStructureModulestoreData
        )

        with mock_registered_transformers(self.registered_transformers):
            with self.assertRaises(TransformerDataIncompatible):
                self.transformers.verify_versions(block_structure)
            self.transformers.collect(block_structure)
            self.assertTrue(self.transformers.verify_versions(block_structure))
