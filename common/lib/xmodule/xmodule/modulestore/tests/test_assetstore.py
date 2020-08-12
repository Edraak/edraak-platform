"""
Tests for assetstore using any of the modulestores for metadata. May extend to testing the storage options
too.
"""
from datetime import datetime, timedelta
import ddt
from django.test import TestCase
import pytz
import unittest

from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locator import CourseLocator

from openedx.core.lib.tests import attr
from xmodule.assetstore import AssetMetadata
from xmodule.modulestore import ModuleStoreEnum, SortedAssetList, IncorrectlySortedList
from xmodule.modulestore.exceptions import ItemNotFoundError
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.tests.utils import (
    MIXED_MODULESTORE_BOTH_SETUP, MODULESTORE_SETUPS,
    XmlModulestoreBuilder, MixedModulestoreBuilder
)


class AssetStoreTestData(object):
    """
    Shared data for constructing test assets.
    """
    now = datetime.now(pytz.utc)
    user_id = 144
    user_id_long = long(user_id)
    user_email = "me@example.com"

    asset_fields = (
        AssetMetadata.ASSET_BASENAME_ATTR, 'internal_name', 'pathname', 'locked',
        'edited_by', 'edited_by_email', 'edited_on', 'created_by', 'created_by_email', 'created_on',
        'curr_version', 'prev_version'
    )
    # pylint: disable=bad-continuation
    all_asset_data = (
        ('pic1.jpg', 'EKMND332DDBK', 'pix/archive', False,
            user_id_long, user_email, now + timedelta(seconds=10 * 1), user_id_long, user_email, now, '14', '13'),
        ('shout.ogg', 'KFMDONSKF39K', 'sounds', True,
            user_id, user_email, now + timedelta(seconds=10 * 2), user_id, user_email, now, '1', None),
        ('code.tgz', 'ZZB2333YBDMW', 'exercises/14', False,
            user_id * 2, user_email, now + timedelta(seconds=10 * 3), user_id * 2, user_email, now, 'AB', 'AA'),
        ('dog.png', 'PUPY4242X', 'pictures/animals', True,
            user_id_long * 3, user_email, now + timedelta(seconds=10 * 4), user_id_long * 3, user_email, now, '5', '4'),
        ('not_here.txt', 'JJJCCC747', '/dev/null', False,
            user_id * 4, user_email, now + timedelta(seconds=10 * 5), user_id * 4, user_email, now, '50', '49'),
        ('asset.txt', 'JJJCCC747858', '/dev/null', False,
            user_id * 4, user_email, now + timedelta(seconds=10 * 6), user_id * 4, user_email, now, '50', '49'),
        ('roman_history.pdf', 'JASDUNSADK', 'texts/italy', True,
            user_id * 7, user_email, now + timedelta(seconds=10 * 7), user_id * 7, user_email, now, '1.1', '1.01'),
        ('weather_patterns.bmp', '928SJXX2EB', 'science', False,
            user_id * 8, user_email, now + timedelta(seconds=10 * 8), user_id * 8, user_email, now, '52', '51'),
        ('demo.swf', 'DFDFGGGG14', 'demos/easy', False,
            user_id * 9, user_email, now + timedelta(seconds=10 * 9), user_id * 9, user_email, now, '5', '4'),
    )


class TestSortedAssetList(unittest.TestCase):
    """
    Tests the SortedAssetList class.
    """
    shard = 1

    def setUp(self):
        super(TestSortedAssetList, self).setUp()
        asset_list = [dict(zip(AssetStoreTestData.asset_fields, asset)) for asset in AssetStoreTestData.all_asset_data]
        self.sorted_asset_list_by_filename = SortedAssetList(iterable=asset_list)
        self.sorted_asset_list_by_last_edit = SortedAssetList(iterable=asset_list, key=lambda x: x['edited_on'])
        self.course_key = CourseLocator('org', 'course', 'run')

    def test_exception_on_bad_sort(self):
        asset_key = self.course_key.make_asset_key('asset', 'pic1.jpg')
        with self.assertRaises(IncorrectlySortedList):
            __ = self.sorted_asset_list_by_last_edit.find(asset_key)

    def test_find(self):
        asset_key = self.course_key.make_asset_key('asset', 'asset.txt')
        self.assertEquals(self.sorted_asset_list_by_filename.find(asset_key), 0)
        asset_key_last = self.course_key.make_asset_key('asset', 'weather_patterns.bmp')
        self.assertEquals(
            self.sorted_asset_list_by_filename.find(asset_key_last), len(AssetStoreTestData.all_asset_data) - 1
        )


@attr('mongo')
@ddt.ddt
class TestMongoAssetMetadataStorage(TestCase):
    """
    Tests for storing/querying course asset metadata.
    """
    shard = 1
    XML_MODULESTORE_MAP = {
        'XML_MODULESTORE_BUILDER': XmlModulestoreBuilder(),
        'MIXED_MODULESTORE_BUILDER': MixedModulestoreBuilder([('xml', XmlModulestoreBuilder())])
    }

    def setUp(self):
        super(TestMongoAssetMetadataStorage, self).setUp()
        self.addTypeEqualityFunc(datetime, self._compare_datetimes)
        self.addTypeEqualityFunc(AssetMetadata, self._compare_metadata)

        self.differents = (('different', 'burn.jpg'),)
        self.vrmls = (
            ('vrml', 'olympus_mons.vrml'),
            ('vrml', 'ponte_vecchio.vrml'),
        )
        self.regular_assets = (('asset', 'zippy.png'),)
        self.alls = self.differents + self.vrmls + self.regular_assets

    def _compare_metadata(self, mdata1, mdata2, msg=None):
        """
        So we can use the below date comparison
        """
        if type(mdata1) != type(mdata2):
            self.fail(self._formatMessage(msg, u"{} is not same type as {}".format(mdata1, mdata2)))
        for attr in mdata1.ATTRS_ALLOWED_TO_UPDATE:
            self.assertEqual(getattr(mdata1, attr), getattr(mdata2, attr), msg)

    def _compare_datetimes(self, datetime1, datetime2, msg=None):
        """
        Don't compare microseconds as mongo doesn't encode below milliseconds
        """
        if not timedelta(seconds=-1) < datetime1 - datetime2 < timedelta(seconds=1):
            self.fail(self._formatMessage(msg, u"{} != {}".format(datetime1, datetime2)))

    def _make_asset_metadata(self, asset_loc):
        """
        Make a single test asset metadata.
        """
        now = datetime.now(pytz.utc)
        return AssetMetadata(
            asset_loc, internal_name='EKMND332DDBK',
            pathname='pictures/historical', contenttype='image/jpeg',
            locked=False, fields={'md5': '77631ca4f0e08419b70726a447333ab6'},
            edited_by=ModuleStoreEnum.UserID.test, edited_on=now,
            created_by=ModuleStoreEnum.UserID.test, created_on=now,
            curr_version='v1.0', prev_version='v0.95'
        )

    def _make_asset_thumbnail_metadata(self, asset_md):
        """
        Add thumbnail to the asset_md
        """
        asset_md.thumbnail = 'ABC39XJUDN2'
        return asset_md

    def setup_assets(self, course1_key, course2_key, store=None):
        """
        Setup assets. Save in store if given
        """
        for i, asset in enumerate(AssetStoreTestData.all_asset_data):
            asset_dict = dict(zip(AssetStoreTestData.asset_fields[1:], asset[1:]))
            if i in (0, 1) and course1_key:
                asset_key = course1_key.make_asset_key('asset', asset[0])
                asset_md = AssetMetadata(asset_key, **asset_dict)
                if store is not None:
                    store.save_asset_metadata(asset_md, asset[4])
            elif course2_key:
                asset_key = course2_key.make_asset_key('asset', asset[0])
                asset_md = AssetMetadata(asset_key, **asset_dict)
                # Don't save assets 5 and 6.
                if store is not None and i not in (4, 5):
                    store.save_asset_metadata(asset_md, asset[4])

    @ddt.data(*MODULESTORE_SETUPS)
    def test_save_one_and_confirm(self, storebuilder):
        """
        Save the metadata in each store and retrieve it singularly, as all assets, and after deleting all.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            asset_filename = 'burnside.jpg'
            new_asset_loc = course.id.make_asset_key('asset', asset_filename)
            # Save the asset's metadata.
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            # Find the asset's metadata and confirm it's the same.
            found_asset_md = store.find_asset_metadata(new_asset_loc)
            self.assertIsNotNone(found_asset_md)
            self.assertEquals(new_asset_md, found_asset_md)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'asset')), 1)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_delete(self, storebuilder):
        """
        Delete non-existent and existent metadata
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('asset', 'burnside.jpg')
            # Attempt to delete an asset that doesn't exist.
            self.assertEquals(store.delete_asset_metadata(new_asset_loc, ModuleStoreEnum.UserID.test), 0)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'asset')), 0)

            new_asset_md = self._make_asset_metadata(new_asset_loc)
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            self.assertEquals(store.delete_asset_metadata(new_asset_loc, ModuleStoreEnum.UserID.test), 1)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'asset')), 0)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_find_non_existing_assets(self, storebuilder):
        """
        Find a non-existent asset in an existing course.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('asset', 'burnside.jpg')
            # Find existing asset metadata.
            asset_md = store.find_asset_metadata(new_asset_loc)
            self.assertIsNone(asset_md)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_get_all_non_existing_assets(self, storebuilder):
        """
        Get all assets in an existing course when no assets exist.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            # Find existing asset metadata.
            asset_md = store.get_all_asset_metadata(course.id, 'asset')
            self.assertEquals(asset_md, [])

    @ddt.data(*MODULESTORE_SETUPS)
    def test_find_assets_in_non_existent_course(self, storebuilder):
        """
        Find asset metadata from a non-existent course.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            fake_course_id = CourseKey.from_string("{}nothere/{}nothere/{}nothere".format(
                course.id.org, course.id.course, course.id.run
            ))
            new_asset_loc = fake_course_id.make_asset_key('asset', 'burnside.jpg')
            # Find asset metadata from non-existent course.
            with self.assertRaises(ItemNotFoundError):
                store.find_asset_metadata(new_asset_loc)
            with self.assertRaises(ItemNotFoundError):
                store.get_all_asset_metadata(fake_course_id, 'asset')

    @ddt.data(*MODULESTORE_SETUPS)
    def test_add_same_asset_twice(self, storebuilder):
        """
        Add an asset's metadata, then add it again.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('asset', 'burnside.jpg')
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            # Add asset metadata.
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'asset')), 1)
            # Add *the same* asset metadata.
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            # Still one here?
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'asset')), 1)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_different_asset_types(self, storebuilder):
        """
        Test saving assets with other asset types.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('vrml', 'pyramid.vrml')
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            # Add asset metadata.
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'vrml')), 1)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'asset')), 0)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_asset_types_with_other_field_names(self, storebuilder):
        """
        Test saving assets using an asset type of 'course_id'.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('course_id', 'just_to_see_if_it_still_works.jpg')
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            # Add asset metadata.
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'course_id')), 1)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'asset')), 0)
            all_assets = store.get_all_asset_metadata(course.id, 'course_id')
            self.assertEquals(all_assets[0].asset_id.path, new_asset_loc.path)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_lock_unlock_assets(self, storebuilder):
        """
        Save multiple metadata in each store and retrieve it singularly, as all assets, and after deleting all.
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('asset', 'burnside.jpg')
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)

            locked_state = new_asset_md.locked
            # Flip the course asset's locked status.
            store.set_asset_metadata_attr(new_asset_loc, "locked", not locked_state, ModuleStoreEnum.UserID.test)
            # Find the same course and check its locked status.
            updated_asset_md = store.find_asset_metadata(new_asset_loc)
            self.assertIsNotNone(updated_asset_md)
            self.assertEquals(updated_asset_md.locked, not locked_state)
            # Now flip it back.
            store.set_asset_metadata_attr(new_asset_loc, "locked", locked_state, ModuleStoreEnum.UserID.test)
            reupdated_asset_md = store.find_asset_metadata(new_asset_loc)
            self.assertIsNotNone(reupdated_asset_md)
            self.assertEquals(reupdated_asset_md.locked, locked_state)

    ALLOWED_ATTRS = (
        ('pathname', '/new/path'),
        ('internal_name', 'new_filename.txt'),
        ('locked', True),
        ('contenttype', 'image/png'),
        ('thumbnail', 'new_filename_thumb.jpg'),
        ('fields', {'md5': '5346682d948cc3f683635b6918f9b3d0'}),
        ('curr_version', 'v1.01'),
        ('prev_version', 'v1.0'),
        ('edited_by', 'Mork'),
        ('edited_on', datetime(1969, 1, 1, tzinfo=pytz.utc)),
    )

    DISALLOWED_ATTRS = (
        ('asset_id', 'IAmBogus'),
        ('created_by', 'Smith'),
        ('created_on', datetime.now(pytz.utc)),
    )

    UNKNOWN_ATTRS = (
        ('lunch_order', 'burger_and_fries'),
        ('villain', 'Khan')
    )

    @ddt.data(*MODULESTORE_SETUPS)
    def test_set_all_attrs(self, storebuilder):
        """
        Save setting each attr one at a time
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('asset', 'burnside.jpg')
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            for attribute, value in self.ALLOWED_ATTRS:
                # Set the course asset's attribute.
                store.set_asset_metadata_attr(new_asset_loc, attribute, value, ModuleStoreEnum.UserID.test)
                # Find the same course asset and check its changed attribute.
                updated_asset_md = store.find_asset_metadata(new_asset_loc)
                self.assertIsNotNone(updated_asset_md)
                self.assertIsNotNone(getattr(updated_asset_md, attribute, None))
                self.assertEquals(getattr(updated_asset_md, attribute, None), value)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_set_disallowed_attrs(self, storebuilder):
        """
        setting disallowed attrs should fail
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('asset', 'burnside.jpg')
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            for attribute, value in self.DISALLOWED_ATTRS:
                original_attr_val = getattr(new_asset_md, attribute)
                # Set the course asset's attribute.
                store.set_asset_metadata_attr(new_asset_loc, attribute, value, ModuleStoreEnum.UserID.test)
                # Find the same course and check its changed attribute.
                updated_asset_md = store.find_asset_metadata(new_asset_loc)
                self.assertIsNotNone(updated_asset_md)
                self.assertIsNotNone(getattr(updated_asset_md, attribute, None))
                # Make sure that the attribute is unchanged from its original value.
                self.assertEquals(getattr(updated_asset_md, attribute, None), original_attr_val)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_set_unknown_attrs(self, storebuilder):
        """
        setting unknown attrs should fail
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            new_asset_loc = course.id.make_asset_key('asset', 'burnside.jpg')
            new_asset_md = self._make_asset_metadata(new_asset_loc)
            store.save_asset_metadata(new_asset_md, ModuleStoreEnum.UserID.test)
            for attribute, value in self.UNKNOWN_ATTRS:
                # Set the course asset's attribute.
                store.set_asset_metadata_attr(new_asset_loc, attribute, value, ModuleStoreEnum.UserID.test)
                # Find the same course and check its changed attribute.
                updated_asset_md = store.find_asset_metadata(new_asset_loc)
                self.assertIsNotNone(updated_asset_md)
                # Make sure the unknown field was *not* added.
                with self.assertRaises(AttributeError):
                    self.assertEquals(getattr(updated_asset_md, attribute), value)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_save_one_different_asset(self, storebuilder):
        """
        saving and deleting things which are not 'asset'
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            asset_key = course.id.make_asset_key('different', 'burn.jpg')
            new_asset_thumbnail = self._make_asset_thumbnail_metadata(
                self._make_asset_metadata(asset_key)
            )
            store.save_asset_metadata(new_asset_thumbnail, ModuleStoreEnum.UserID.test)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'different')), 1)
            self.assertEquals(store.delete_asset_metadata(asset_key, ModuleStoreEnum.UserID.test), 1)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'different')), 0)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_find_different(self, storebuilder):
        """
        finding things which are of type other than 'asset'
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            asset_key = course.id.make_asset_key('different', 'burn.jpg')
            new_asset_thumbnail = self._make_asset_thumbnail_metadata(
                self._make_asset_metadata(asset_key)
            )
            store.save_asset_metadata(new_asset_thumbnail, ModuleStoreEnum.UserID.test)

            self.assertIsNotNone(store.find_asset_metadata(asset_key))
            unknown_asset_key = course.id.make_asset_key('different', 'nosuchfile.jpg')
            self.assertIsNone(store.find_asset_metadata(unknown_asset_key))

    def _check_asset_values(self, assets, orig):
        """
        Check asset type/path values.
        """
        for idx, asset in enumerate(orig):
            self.assertEquals(assets[idx].asset_id.asset_type, asset[0])
            self.assertEquals(assets[idx].asset_id.path, asset[1])

    @ddt.data(*MODULESTORE_SETUPS)
    def test_get_multiple_types(self, storebuilder):
        """
        getting all things which are of type other than 'asset'
        """
        # pylint: disable=bad-continuation
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)

            # Save 'em.
            for asset_type, filename in self.alls:
                asset_key = course.id.make_asset_key(asset_type, filename)
                new_asset = self._make_asset_thumbnail_metadata(
                    self._make_asset_metadata(asset_key)
                )
                store.save_asset_metadata(new_asset, ModuleStoreEnum.UserID.test)

            # Check 'em.
            for asset_type, asset_list in (
                ('different', self.differents),
                ('vrml', self.vrmls),
                ('asset', self.regular_assets),
            ):
                assets = store.get_all_asset_metadata(course.id, asset_type)
                self.assertEquals(len(assets), len(asset_list))
                self._check_asset_values(assets, asset_list)

            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'not_here')), 0)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, None)), 4)

            assets = store.get_all_asset_metadata(
                course.id, None, start=0, maxresults=-1,
                sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(assets), len(self.alls))
            self._check_asset_values(assets, self.alls)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_save_metadata_list(self, storebuilder):
        """
        Save a list of asset metadata all at once.
        """
        # pylint: disable=bad-continuation
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)

            # Make a list of AssetMetadata objects.
            md_list = []
            for asset_type, filename in self.alls:
                asset_key = course.id.make_asset_key(asset_type, filename)
                md_list.append(self._make_asset_thumbnail_metadata(
                    self._make_asset_metadata(asset_key)
                ))

            # Save 'em.
            store.save_asset_metadata_list(md_list, ModuleStoreEnum.UserID.test)

            # Check 'em.
            for asset_type, asset_list in (
                ('different', self.differents),
                ('vrml', self.vrmls),
                ('asset', self.regular_assets),
            ):
                assets = store.get_all_asset_metadata(course.id, asset_type)
                self.assertEquals(len(assets), len(asset_list))
                self._check_asset_values(assets, asset_list)

            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'not_here')), 0)
            self.assertEquals(len(store.get_all_asset_metadata(course.id, None)), 4)

            assets = store.get_all_asset_metadata(
                course.id, None, start=0, maxresults=-1,
                sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(assets), len(self.alls))
            self._check_asset_values(assets, self.alls)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_save_metadata_list_with_mismatched_asset(self, storebuilder):
        """
        Save a list of asset metadata all at once - but with one asset's metadata from a different course.
        """
        # pylint: disable=bad-continuation
        with storebuilder.build() as (__, store):
            course1 = CourseFactory.create(modulestore=store)
            course2 = CourseFactory.create(modulestore=store)

            # Make a list of AssetMetadata objects.
            md_list = []
            for asset_type, filename in self.alls:
                if asset_type == 'asset':
                    asset_key = course2.id.make_asset_key(asset_type, filename)
                else:
                    asset_key = course1.id.make_asset_key(asset_type, filename)
                md_list.append(self._make_asset_thumbnail_metadata(
                    self._make_asset_metadata(asset_key)
                ))

            # Save 'em.
            store.save_asset_metadata_list(md_list, ModuleStoreEnum.UserID.test)

            # Check 'em.
            for asset_type, asset_list in (
                ('different', self.differents),
                ('vrml', self.vrmls),
            ):
                assets = store.get_all_asset_metadata(course1.id, asset_type)
                self.assertEquals(len(assets), len(asset_list))
                self._check_asset_values(assets, asset_list)

            self.assertEquals(len(store.get_all_asset_metadata(course1.id, 'asset')), 0)
            self.assertEquals(len(store.get_all_asset_metadata(course1.id, None)), 3)

            assets = store.get_all_asset_metadata(
                course1.id, None, start=0, maxresults=-1,
                sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(assets), len(self.differents + self.vrmls))
            self._check_asset_values(assets, self.differents + self.vrmls)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_delete_all_different_type(self, storebuilder):
        """
        deleting all assets of a given but not 'asset' type
        """
        with storebuilder.build() as (__, store):
            course = CourseFactory.create(modulestore=store)
            asset_key = course.id.make_asset_key('different', 'burn_thumb.jpg')
            new_asset_thumbnail = self._make_asset_thumbnail_metadata(
                self._make_asset_metadata(asset_key)
            )
            store.save_asset_metadata(new_asset_thumbnail, ModuleStoreEnum.UserID.test)

            self.assertEquals(len(store.get_all_asset_metadata(course.id, 'different')), 1)

    @ddt.data(*MODULESTORE_SETUPS)
    def test_get_all_assets_with_paging(self, storebuilder):
        """
        Save multiple metadata in each store and retrieve it singularly, as all assets, and after deleting all.
        """
        with storebuilder.build() as (__, store):
            course1 = CourseFactory.create(modulestore=store)
            course2 = CourseFactory.create(modulestore=store)
            self.setup_assets(course1.id, course2.id, store)

            expected_sorts_by_2 = (
                (
                    ('displayname', ModuleStoreEnum.SortOrder.ascending),
                    ('code.tgz', 'demo.swf', 'dog.png', 'roman_history.pdf', 'weather_patterns.bmp'),
                    (2, 2, 1)
                ),
                (
                    ('displayname', ModuleStoreEnum.SortOrder.descending),
                    ('weather_patterns.bmp', 'roman_history.pdf', 'dog.png', 'demo.swf', 'code.tgz'),
                    (2, 2, 1)
                ),
                (
                    ('uploadDate', ModuleStoreEnum.SortOrder.ascending),
                    ('code.tgz', 'dog.png', 'roman_history.pdf', 'weather_patterns.bmp', 'demo.swf'),
                    (2, 2, 1)
                ),
                (
                    ('uploadDate', ModuleStoreEnum.SortOrder.descending),
                    ('demo.swf', 'weather_patterns.bmp', 'roman_history.pdf', 'dog.png', 'code.tgz'),
                    (2, 2, 1)
                ),
            )
            # First, with paging across all sorts.
            for sort_test in expected_sorts_by_2:
                for i in xrange(3):
                    asset_page = store.get_all_asset_metadata(
                        course2.id, 'asset', start=2 * i, maxresults=2, sort=sort_test[0]
                    )
                    num_expected_results = sort_test[2][i]
                    expected_filename = sort_test[1][2 * i]
                    self.assertEquals(len(asset_page), num_expected_results)
                    self.assertEquals(asset_page[0].asset_id.path, expected_filename)
                    if num_expected_results == 2:
                        expected_filename = sort_test[1][(2 * i) + 1]
                        self.assertEquals(asset_page[1].asset_id.path, expected_filename)

            # Now fetch everything.
            asset_page = store.get_all_asset_metadata(
                course2.id, 'asset', start=0, sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(asset_page), 5)
            self.assertEquals(asset_page[0].asset_id.path, 'code.tgz')
            self.assertEquals(asset_page[1].asset_id.path, 'demo.swf')
            self.assertEquals(asset_page[2].asset_id.path, 'dog.png')
            self.assertEquals(asset_page[3].asset_id.path, 'roman_history.pdf')
            self.assertEquals(asset_page[4].asset_id.path, 'weather_patterns.bmp')

            # Some odd conditions.
            asset_page = store.get_all_asset_metadata(
                course2.id, 'asset', start=100, sort=('uploadDate', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(asset_page), 0)
            asset_page = store.get_all_asset_metadata(
                course2.id, 'asset', start=3, maxresults=0,
                sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(asset_page), 0)
            asset_page = store.get_all_asset_metadata(
                course2.id, 'asset', start=3, maxresults=-12345,
                sort=('displayname', ModuleStoreEnum.SortOrder.descending)
            )
            self.assertEquals(len(asset_page), 2)

    @ddt.data('XML_MODULESTORE_BUILDER', 'MIXED_MODULESTORE_BUILDER')
    def test_xml_not_yet_implemented(self, storebuilderName):
        """
        Test coverage which shows that for now xml read operations are not implemented
        """
        storebuilder = self.XML_MODULESTORE_MAP[storebuilderName]
        with storebuilder.build(contentstore=None) as (__, store):
            course_key = store.make_course_key("org", "course", "run")
            asset_key = course_key.make_asset_key('asset', 'foo.jpg')
            self.assertEquals(store.find_asset_metadata(asset_key), None)
            self.assertEquals(store.get_all_asset_metadata(course_key, 'asset'), [])

    @ddt.data(*MODULESTORE_SETUPS)
    def test_copy_all_assets_same_modulestore(self, storebuilder):
        """
        Create a course with assets, copy them all to another course in the same modulestore, and check on it.
        """
        with storebuilder.build() as (__, store):
            course1 = CourseFactory.create(modulestore=store)
            course2 = CourseFactory.create(modulestore=store)
            self.setup_assets(course1.id, None, store)
            self.assertEquals(len(store.get_all_asset_metadata(course1.id, 'asset')), 2)
            self.assertEquals(len(store.get_all_asset_metadata(course2.id, 'asset')), 0)
            store.copy_all_asset_metadata(course1.id, course2.id, ModuleStoreEnum.UserID.test * 101)
            self.assertEquals(len(store.get_all_asset_metadata(course1.id, 'asset')), 2)
            all_assets = store.get_all_asset_metadata(
                course2.id, 'asset', sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(all_assets), 2)
            self.assertEquals(all_assets[0].asset_id.path, 'pic1.jpg')
            self.assertEquals(all_assets[1].asset_id.path, 'shout.ogg')

    @ddt.data(*MODULESTORE_SETUPS)
    def test_copy_all_assets_from_course_with_no_assets(self, storebuilder):
        """
        Create a course with *no* assets, and try copy them all to another course in the same modulestore.
        """
        with storebuilder.build() as (__, store):
            course1 = CourseFactory.create(modulestore=store)
            course2 = CourseFactory.create(modulestore=store)
            store.copy_all_asset_metadata(course1.id, course2.id, ModuleStoreEnum.UserID.test * 101)
            self.assertEquals(len(store.get_all_asset_metadata(course1.id, 'asset')), 0)
            self.assertEquals(len(store.get_all_asset_metadata(course2.id, 'asset')), 0)
            all_assets = store.get_all_asset_metadata(
                course2.id, 'asset', sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(all_assets), 0)

    @ddt.data(
        ('mongo', 'split'),
        ('split', 'mongo'),
    )
    @ddt.unpack
    def test_copy_all_assets_cross_modulestore(self, from_store, to_store):
        """
        Create a course with assets, copy them all to another course in a different modulestore, and check on it.
        """
        mixed_builder = MIXED_MODULESTORE_BOTH_SETUP
        with mixed_builder.build() as (__, mixed_store):
            with mixed_store.default_store(from_store):
                course1 = CourseFactory.create(modulestore=mixed_store)
            with mixed_store.default_store(to_store):
                course2 = CourseFactory.create(modulestore=mixed_store)
            self.setup_assets(course1.id, None, mixed_store)
            self.assertEquals(len(mixed_store.get_all_asset_metadata(course1.id, 'asset')), 2)
            self.assertEquals(len(mixed_store.get_all_asset_metadata(course2.id, 'asset')), 0)
            mixed_store.copy_all_asset_metadata(course1.id, course2.id, ModuleStoreEnum.UserID.test * 102)
            all_assets = mixed_store.get_all_asset_metadata(
                course2.id, 'asset', sort=('displayname', ModuleStoreEnum.SortOrder.ascending)
            )
            self.assertEquals(len(all_assets), 2)
            self.assertEquals(all_assets[0].asset_id.path, 'pic1.jpg')
            self.assertEquals(all_assets[1].asset_id.path, 'shout.ogg')
