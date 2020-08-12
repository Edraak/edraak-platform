"""
Unit tests for course import and export
"""
import copy
import json
import logging
import os
import shutil
import tarfile
import tempfile
from uuid import uuid4

import ddt
import lxml
from django.conf import settings
from django.test.utils import override_settings
from milestones.tests.utils import MilestonesTestCaseMixin
from opaque_keys.edx.locator import LibraryLocator
from path import Path as path

from contentstore.tests.test_libraries import LibraryTestCase
from contentstore.tests.utils import CourseTestCase
from contentstore.utils import reverse_course_url
from models.settings.course_metadata import CourseMetadata
from openedx.core.lib.extract_tar import safetar_extractall
from student import auth
from student.roles import CourseInstructorRole, CourseStaffRole
from util import milestones_helpers
from xmodule.contentstore.django import contentstore
from xmodule.modulestore import LIBRARY_ROOT, ModuleStoreEnum
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory, LibraryFactory
from xmodule.modulestore.tests.utils import SPLIT_MODULESTORE_SETUP, TEST_DATA_DIR, MongoContentstoreBuilder
from xmodule.modulestore.xml_exporter import export_course_to_xml, export_library_to_xml
from xmodule.modulestore.xml_importer import import_course_from_xml, import_library_from_xml

TEST_DATA_CONTENTSTORE = copy.deepcopy(settings.CONTENTSTORE)
TEST_DATA_CONTENTSTORE['DOC_STORE_CONFIG']['db'] = 'test_xcontent_%s' % uuid4().hex
TEST_DATA_DIR = settings.COMMON_TEST_DATA_ROOT

log = logging.getLogger(__name__)


@override_settings(CONTENTSTORE=TEST_DATA_CONTENTSTORE)
class ImportEntranceExamTestCase(CourseTestCase, MilestonesTestCaseMixin):
    """
    Unit tests for importing a course with entrance exam
    """
    def setUp(self):
        super(ImportEntranceExamTestCase, self).setUp()
        self.url = reverse_course_url('import_handler', self.course.id)
        self.content_dir = path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.content_dir)

        # Create tar test file -----------------------------------------------
        # OK course with entrance exam section:
        entrance_exam_dir = tempfile.mkdtemp(dir=self.content_dir)
        # test course being deeper down than top of tar file
        embedded_exam_dir = os.path.join(entrance_exam_dir, "grandparent", "parent")
        os.makedirs(os.path.join(embedded_exam_dir, "course"))
        os.makedirs(os.path.join(embedded_exam_dir, "chapter"))
        with open(os.path.join(embedded_exam_dir, "course.xml"), "w+") as f:
            f.write('<course url_name="2013_Spring" org="EDx" course="0.00x"/>')

        with open(os.path.join(embedded_exam_dir, "course", "2013_Spring.xml"), "w+") as f:
            f.write(
                '<course '
                'entrance_exam_enabled="true" entrance_exam_id="xyz" entrance_exam_minimum_score_pct="0.7">'
                '<chapter url_name="2015_chapter_entrance_exam"/></course>'
            )

        with open(os.path.join(embedded_exam_dir, "chapter", "2015_chapter_entrance_exam.xml"), "w+") as f:
            f.write('<chapter display_name="Entrance Exam" in_entrance_exam="true" is_entrance_exam="true"></chapter>')

        self.entrance_exam_tar = os.path.join(self.content_dir, "entrance_exam.tar.gz")
        with tarfile.open(self.entrance_exam_tar, "w:gz") as gtar:
            gtar.add(entrance_exam_dir)

    def test_import_existing_entrance_exam_course(self):
        """
        Check that course is imported successfully as an entrance exam.
        """
        course = self.store.get_course(self.course.id)
        self.assertIsNotNone(course)
        self.assertEquals(course.entrance_exam_enabled, False)

        with open(self.entrance_exam_tar) as gtar:
            args = {"name": self.entrance_exam_tar, "course-data": [gtar]}
            resp = self.client.post(self.url, args)
        self.assertEquals(resp.status_code, 200)
        course = self.store.get_course(self.course.id)
        self.assertIsNotNone(course)
        self.assertEquals(course.entrance_exam_enabled, True)
        self.assertEquals(course.entrance_exam_minimum_score_pct, 0.7)

    def test_import_delete_pre_exiting_entrance_exam(self):
        """
        Check that pre existed entrance exam content should be overwrite with the imported course.
        """
        exam_url = '/course/{}/entrance_exam/'.format(unicode(self.course.id))
        resp = self.client.post(exam_url, {'entrance_exam_minimum_score_pct': 0.5}, http_accept='application/json')
        self.assertEqual(resp.status_code, 201)

        # Reload the test course now that the exam module has been added
        self.course = modulestore().get_course(self.course.id)
        metadata = CourseMetadata.fetch_all(self.course)
        self.assertTrue(metadata['entrance_exam_enabled'])
        self.assertIsNotNone(metadata['entrance_exam_minimum_score_pct'])
        self.assertEqual(metadata['entrance_exam_minimum_score_pct']['value'], 0.5)
        self.assertTrue(len(milestones_helpers.get_course_milestones(unicode(self.course.id))))
        content_milestones = milestones_helpers.get_course_content_milestones(
            unicode(self.course.id),
            metadata['entrance_exam_id']['value'],
            milestones_helpers.get_milestone_relationship_types()['FULFILLS']
        )
        self.assertTrue(len(content_milestones))

        # Now import entrance exam course
        with open(self.entrance_exam_tar) as gtar:
            args = {"name": self.entrance_exam_tar, "course-data": [gtar]}
            resp = self.client.post(self.url, args)
        self.assertEquals(resp.status_code, 200)
        course = self.store.get_course(self.course.id)
        self.assertIsNotNone(course)
        self.assertEquals(course.entrance_exam_enabled, True)
        self.assertEquals(course.entrance_exam_minimum_score_pct, 0.7)


@ddt.ddt
@override_settings(CONTENTSTORE=TEST_DATA_CONTENTSTORE)
class ImportTestCase(CourseTestCase):
    """
    Unit tests for importing a course or Library
    """
    def setUp(self):
        super(ImportTestCase, self).setUp()
        self.url = reverse_course_url('import_handler', self.course.id)
        self.content_dir = path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.content_dir)

        def touch(name):
            """ Equivalent to shell's 'touch'"""
            with file(name, 'a'):
                os.utime(name, None)

        # Create tar test files -----------------------------------------------
        # OK course:
        good_dir = tempfile.mkdtemp(dir=self.content_dir)
        # test course being deeper down than top of tar file
        embedded_dir = os.path.join(good_dir, "grandparent", "parent")
        os.makedirs(os.path.join(embedded_dir, "course"))
        with open(os.path.join(embedded_dir, "course.xml"), "w+") as f:
            f.write('<course url_name="2013_Spring" org="EDx" course="0.00x"/>')

        with open(os.path.join(embedded_dir, "course", "2013_Spring.xml"), "w+") as f:
            f.write('<course></course>')

        self.good_tar = os.path.join(self.content_dir, "good.tar.gz")
        with tarfile.open(self.good_tar, "w:gz") as gtar:
            gtar.add(good_dir)

        # Bad course (no 'course.xml' file):
        bad_dir = tempfile.mkdtemp(dir=self.content_dir)
        touch(os.path.join(bad_dir, "bad.xml"))
        self.bad_tar = os.path.join(self.content_dir, "bad.tar.gz")
        with tarfile.open(self.bad_tar, "w:gz") as btar:
            btar.add(bad_dir)

        self.unsafe_common_dir = path(tempfile.mkdtemp(dir=self.content_dir))

    def test_no_coursexml(self):
        """
        Check that the response for a tar.gz import without a course.xml is
        correct.
        """
        with open(self.bad_tar) as btar:
            resp = self.client.post(
                self.url,
                {
                    "name": self.bad_tar,
                    "course-data": [btar]
                })
        self.assertEquals(resp.status_code, 200)
        # Check that `import_status` returns the appropriate stage (i.e., the
        # stage at which import failed).
        resp_status = self.client.get(
            reverse_course_url(
                'import_status_handler',
                self.course.id,
                kwargs={'filename': os.path.split(self.bad_tar)[1]}
            )
        )

        self.assertEquals(json.loads(resp_status.content)["ImportStatus"], -2)

    def test_with_coursexml(self):
        """
        Check that the response for a tar.gz import with a course.xml is
        correct.
        """
        with open(self.good_tar) as gtar:
            args = {"name": self.good_tar, "course-data": [gtar]}
            resp = self.client.post(self.url, args)

        self.assertEquals(resp.status_code, 200)

    def test_import_in_existing_course(self):
        """
        Check that course is imported successfully in existing course and users have their access roles
        """
        # Create a non_staff user and add it to course staff only
        __, nonstaff_user = self.create_non_staff_authed_user_client()
        auth.add_users(self.user, CourseStaffRole(self.course.id), nonstaff_user)

        course = self.store.get_course(self.course.id)
        self.assertIsNotNone(course)
        display_name_before_import = course.display_name

        # Check that global staff user can import course
        with open(self.good_tar) as gtar:
            args = {"name": self.good_tar, "course-data": [gtar]}
            resp = self.client.post(self.url, args)
        self.assertEquals(resp.status_code, 200)

        course = self.store.get_course(self.course.id)
        self.assertIsNotNone(course)
        display_name_after_import = course.display_name

        # Check that course display name have changed after import
        self.assertNotEqual(display_name_before_import, display_name_after_import)

        # Now check that non_staff user has his same role
        self.assertFalse(CourseInstructorRole(self.course.id).has_user(nonstaff_user))
        self.assertTrue(CourseStaffRole(self.course.id).has_user(nonstaff_user))

        # Now course staff user can also successfully import course
        self.client.login(username=nonstaff_user.username, password='foo')
        with open(self.good_tar) as gtar:
            args = {"name": self.good_tar, "course-data": [gtar]}
            resp = self.client.post(self.url, args)
        self.assertEquals(resp.status_code, 200)

        # Now check that non_staff user has his same role
        self.assertFalse(CourseInstructorRole(self.course.id).has_user(nonstaff_user))
        self.assertTrue(CourseStaffRole(self.course.id).has_user(nonstaff_user))

    ## Unsafe tar methods #####################################################
    # Each of these methods creates a tarfile with a single type of unsafe
    # content.
    def _fifo_tar(self):
        """
        Tar file with FIFO
        """
        fifop = self.unsafe_common_dir / "fifo.file"
        fifo_tar = self.unsafe_common_dir / "fifo.tar.gz"
        os.mkfifo(fifop)
        with tarfile.open(fifo_tar, "w:gz") as tar:
            tar.add(fifop)

        return fifo_tar

    def _symlink_tar(self):
        """
        Tarfile with symlink to path outside directory.
        """
        outsidep = self.unsafe_common_dir / "unsafe_file.txt"
        symlinkp = self.unsafe_common_dir / "symlink.txt"
        symlink_tar = self.unsafe_common_dir / "symlink.tar.gz"
        outsidep.symlink(symlinkp)
        with tarfile.open(symlink_tar, "w:gz") as tar:
            tar.add(symlinkp)

        return symlink_tar

    def _outside_tar(self):
        """
        Tarfile with file that extracts to outside directory.

        Extracting this tarfile in directory <dir> will put its contents
        directly in <dir> (rather than <dir/tarname>).
        """
        outside_tar = self.unsafe_common_dir / "unsafe_file.tar.gz"
        with tarfile.open(outside_tar, "w:gz") as tar:
            tar.addfile(tarfile.TarInfo(str(self.content_dir / "a_file")))

        return outside_tar

    def _outside_tar2(self):
        """
        Tarfile with file that extracts to outside directory.

        The path here matches the basename (`self.unsafe_common_dir`), but
        then "cd's out". E.g. "/usr/../etc" == "/etc", but the naive basename
        of the first (but not the second) is "/usr"

        Extracting this tarfile in directory <dir> will also put its contents
        directly in <dir> (rather than <dir/tarname>).
        """
        outside_tar = self.unsafe_common_dir / "unsafe_file.tar.gz"
        with tarfile.open(outside_tar, "w:gz") as tar:
            tar.addfile(tarfile.TarInfo(str(self.unsafe_common_dir / "../a_file")))

        return outside_tar

    def _edx_platform_tar(self):
        """
        Tarfile with file that extracts to edx-platform directory.

        Extracting this tarfile in directory <dir> will also put its contents
        directly in <dir> (rather than <dir/tarname>).
        """
        outside_tar = self.unsafe_common_dir / "unsafe_file.tar.gz"
        with tarfile.open(outside_tar, "w:gz") as tar:
            tar.addfile(tarfile.TarInfo(os.path.join(os.path.abspath("."), "a_file")))

        return outside_tar

    def test_unsafe_tar(self):
        """
        Check that safety measure work.

        This includes:
            'tarbombs' which include files or symlinks with paths
        outside or directly in the working directory,
            'special files' (character device, block device or FIFOs),

        all raise exceptions/400s.
        """

        def try_tar(tarpath):
            """ Attempt to tar an unacceptable file """
            with open(tarpath) as tar:
                args = {"name": tarpath, "course-data": [tar]}
                resp = self.client.post(self.url, args)
            self.assertEquals(resp.status_code, 200)
            resp = self.client.get(
                reverse_course_url(
                    'import_status_handler',
                    self.course.id,
                    kwargs={'filename': os.path.split(tarpath)[1]}
                )
            )
            status = json.loads(resp.content)["ImportStatus"]
            self.assertEqual(status, -1)

        try_tar(self._fifo_tar())
        try_tar(self._symlink_tar())
        try_tar(self._outside_tar())
        try_tar(self._outside_tar2())
        try_tar(self._edx_platform_tar())

        # test trying to open a tar outside of the normal data directory
        with self.settings(DATA_DIR='/not/the/data/dir'):
            try_tar(self._edx_platform_tar())

        # Check that `import_status` returns the appropriate stage (i.e.,
        # either 3, indicating all previous steps are completed, or 0,
        # indicating no upload in progress)
        resp_status = self.client.get(
            reverse_course_url(
                'import_status_handler',
                self.course.id,
                kwargs={'filename': os.path.split(self.good_tar)[1]}
            )
        )
        import_status = json.loads(resp_status.content)["ImportStatus"]
        self.assertIn(import_status, (0, 3))

    def test_library_import(self):
        """
        Try importing a known good library archive, and verify that the
        contents of the library have completely replaced the old contents.
        """
        # Create some blocks to overwrite
        library = LibraryFactory.create(modulestore=self.store)
        lib_key = library.location.library_key
        test_block = ItemFactory.create(
            category="vertical",
            parent_location=library.location,
            user_id=self.user.id,
            publish_item=False,
        )
        test_block2 = ItemFactory.create(
            category="vertical",
            parent_location=library.location,
            user_id=self.user.id,
            publish_item=False
        )
        # Create a library and blocks that should remain unmolested.
        unchanged_lib = LibraryFactory.create()
        unchanged_key = unchanged_lib.location.library_key
        test_block3 = ItemFactory.create(
            category="vertical",
            parent_location=unchanged_lib.location,
            user_id=self.user.id,
            publish_item=False
        )
        test_block4 = ItemFactory.create(
            category="vertical",
            parent_location=unchanged_lib.location,
            user_id=self.user.id,
            publish_item=False
        )
        # Refresh library.
        library = self.store.get_library(lib_key)
        children = [self.store.get_item(child).url_name for child in library.children]
        self.assertEqual(len(children), 2)
        self.assertIn(test_block.url_name, children)
        self.assertIn(test_block2.url_name, children)

        unchanged_lib = self.store.get_library(unchanged_key)
        children = [self.store.get_item(child).url_name for child in unchanged_lib.children]
        self.assertEqual(len(children), 2)
        self.assertIn(test_block3.url_name, children)
        self.assertIn(test_block4.url_name, children)

        extract_dir = path(tempfile.mkdtemp(dir=settings.DATA_DIR))
        # the extract_dir needs to be passed as a relative dir to
        # import_library_from_xml
        extract_dir_relative = path.relpath(extract_dir, settings.DATA_DIR)

        try:
            with tarfile.open(path(TEST_DATA_DIR) / 'imports' / 'library.HhJfPD.tar.gz') as tar:
                safetar_extractall(tar, extract_dir)
            library_items = import_library_from_xml(
                self.store,
                self.user.id,
                settings.GITHUB_REPO_ROOT,
                [extract_dir_relative / 'library'],
                load_error_modules=False,
                static_content_store=contentstore(),
                target_id=lib_key
            )
        finally:
            shutil.rmtree(extract_dir)

        self.assertEqual(lib_key, library_items[0].location.library_key)
        library = self.store.get_library(lib_key)
        children = [self.store.get_item(child).url_name for child in library.children]
        self.assertEqual(len(children), 3)
        self.assertNotIn(test_block.url_name, children)
        self.assertNotIn(test_block2.url_name, children)

        unchanged_lib = self.store.get_library(unchanged_key)
        children = [self.store.get_item(child).url_name for child in unchanged_lib.children]
        self.assertEqual(len(children), 2)
        self.assertIn(test_block3.url_name, children)
        self.assertIn(test_block4.url_name, children)

    @ddt.data(
        ModuleStoreEnum.Branch.draft_preferred,
        ModuleStoreEnum.Branch.published_only,
    )
    def test_library_import_branch_settings(self, branch_setting):
        """
        Try importing a known good library archive under either branch setting.
        The branch setting should have no effect on library import.
        """
        with self.store.branch_setting(branch_setting):
            library = LibraryFactory.create(modulestore=self.store)
            lib_key = library.location.library_key
            extract_dir = path(tempfile.mkdtemp(dir=settings.DATA_DIR))
            # the extract_dir needs to be passed as a relative dir to
            # import_library_from_xml
            extract_dir_relative = path.relpath(extract_dir, settings.DATA_DIR)

            try:
                with tarfile.open(path(TEST_DATA_DIR) / 'imports' / 'library.HhJfPD.tar.gz') as tar:
                    safetar_extractall(tar, extract_dir)
                import_library_from_xml(
                    self.store,
                    self.user.id,
                    settings.GITHUB_REPO_ROOT,
                    [extract_dir_relative / 'library'],
                    load_error_modules=False,
                    static_content_store=contentstore(),
                    target_id=lib_key
                )
            finally:
                shutil.rmtree(extract_dir)

    @ddt.data(
        ModuleStoreEnum.Branch.draft_preferred,
        ModuleStoreEnum.Branch.published_only,
    )
    def test_library_import_branch_settings_again(self, branch_setting):
        # Construct the contentstore for storing the import
        with MongoContentstoreBuilder().build() as source_content:
            # Construct the modulestore for storing the import (using the previously created contentstore)
            with SPLIT_MODULESTORE_SETUP.build(contentstore=source_content) as source_store:
                # Use the test branch setting.
                with source_store.branch_setting(branch_setting):
                    source_library_key = LibraryLocator(org='TestOrg', library='TestProbs')

                    extract_dir = path(tempfile.mkdtemp(dir=settings.DATA_DIR))
                    # the extract_dir needs to be passed as a relative dir to
                    # import_library_from_xml
                    extract_dir_relative = path.relpath(extract_dir, settings.DATA_DIR)

                    try:
                        with tarfile.open(path(TEST_DATA_DIR) / 'imports' / 'library.HhJfPD.tar.gz') as tar:
                            safetar_extractall(tar, extract_dir)
                        import_library_from_xml(
                            source_store,
                            self.user.id,
                            settings.GITHUB_REPO_ROOT,
                            [extract_dir_relative / 'library'],
                            static_content_store=source_content,
                            target_id=source_library_key,
                            load_error_modules=False,
                            raise_on_failure=True,
                            create_if_not_present=True,
                        )
                    finally:
                        shutil.rmtree(extract_dir)


@override_settings(CONTENTSTORE=TEST_DATA_CONTENTSTORE)
@ddt.ddt
class ExportTestCase(CourseTestCase):
    """
    Tests for export_handler.
    """
    def setUp(self):
        """
        Sets up the test course.
        """
        super(ExportTestCase, self).setUp()
        self.url = reverse_course_url('export_handler', self.course.id)
        self.status_url = reverse_course_url('export_status_handler', self.course.id)

    def test_export_html(self):
        """
        Get the HTML for the page.
        """
        resp = self.client.get_html(self.url)
        self.assertEquals(resp.status_code, 200)
        self.assertContains(resp, "Export My Course Content")

    def test_export_json_unsupported(self):
        """
        JSON is unsupported.
        """
        resp = self.client.get(self.url, HTTP_ACCEPT='application/json')
        self.assertEquals(resp.status_code, 406)

    def test_export_async(self):
        """
        Get tar.gz file, using asynchronous background task
        """
        resp = self.client.post(self.url)
        self.assertEquals(resp.status_code, 200)
        resp = self.client.get(self.status_url)
        result = json.loads(resp.content)
        status = result['ExportStatus']
        self.assertEquals(status, 3)
        self.assertIn('ExportOutput', result)
        output_url = result['ExportOutput']
        resp = self.client.get(output_url)
        self._verify_export_succeeded(resp)

    def _verify_export_succeeded(self, resp):
        """ Export success helper method. """
        self.assertEquals(resp.status_code, 200)
        self.assertTrue(resp.get('Content-Disposition').startswith('attachment'))

    def test_export_failure_top_level(self):
        """
        Export failure.
        """
        fake_xblock = ItemFactory.create(parent_location=self.course.location, category='aawefawef')
        self.store.publish(fake_xblock.location, self.user.id)
        self._verify_export_failure(u'/container/{}'.format(self.course.location))

    def test_export_failure_subsection_level(self):
        """
        Slightly different export failure.
        """
        vertical = ItemFactory.create(parent_location=self.course.location, category='vertical', display_name='foo')
        ItemFactory.create(
            parent_location=vertical.location,
            category='aawefawef'
        )

        self._verify_export_failure(u'/container/{}'.format(vertical.location))

    def _verify_export_failure(self, expected_text):
        """ Export failure helper method. """
        resp = self.client.post(self.url)
        self.assertEquals(resp.status_code, 200)
        resp = self.client.get(self.status_url)
        self.assertEquals(resp.status_code, 200)
        result = json.loads(resp.content)
        self.assertNotIn('ExportOutput', result)
        self.assertIn('ExportError', result)
        error = result['ExportError']
        self.assertIn('Unable to create xml for module', error['raw_error_msg'])
        self.assertIn(expected_text, error['edit_unit_url'])

    def test_library_export(self):
        """
        Verify that useable library data can be exported.
        """
        youtube_id = "qS4NO9MNC6w"
        library = LibraryFactory.create(modulestore=self.store)
        video_block = ItemFactory.create(
            category="video",
            parent_location=library.location,
            user_id=self.user.id,
            publish_item=False,
            youtube_id_1_0=youtube_id
        )
        name = library.url_name
        lib_key = library.location.library_key
        root_dir = path(tempfile.mkdtemp())
        try:
            export_library_to_xml(self.store, contentstore(), lib_key, root_dir, name)
            lib_xml = lxml.etree.XML(open(root_dir / name / LIBRARY_ROOT).read())
            self.assertEqual(lib_xml.get('org'), lib_key.org)
            self.assertEqual(lib_xml.get('library'), lib_key.library)
            block = lib_xml.find('video')
            self.assertIsNotNone(block)
            self.assertEqual(block.get('url_name'), video_block.url_name)
            video_xml = lxml.etree.XML(open(root_dir / name / 'video' / video_block.url_name + '.xml').read())
            self.assertEqual(video_xml.tag, 'video')
            self.assertEqual(video_xml.get('youtube_id_1_0'), youtube_id)
        finally:
            shutil.rmtree(root_dir / name)

    def test_export_success_with_custom_tag(self):
        """
        Verify that course export with customtag
        """
        xml_string = '<impl>slides</impl>'
        vertical = ItemFactory.create(
            parent_location=self.course.location, category='vertical', display_name='foo'
        )
        ItemFactory.create(
            parent_location=vertical.location,
            category='customtag',
            display_name='custom_tag_foo',
            data=xml_string
        )

        self.test_export_async()

    @ddt.data(
        '/export/non.1/existence_1/Run_1',  # For mongo
        '/export/course-v1:non1+existence1+Run1',  # For split
    )
    def test_export_course_does_not_exist(self, url):
        """
        Export failure if course does not exist
        """
        resp = self.client.get_html(url)
        self.assertEquals(resp.status_code, 404)

    def test_non_course_author(self):
        """
        Verify that users who aren't authors of the course are unable to export it
        """
        client, _ = self.create_non_staff_authed_user_client()
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_status_non_course_author(self):
        """
        Verify that users who aren't authors of the course are unable to see the status of export tasks
        """
        client, _ = self.create_non_staff_authed_user_client()
        resp = client.get(self.status_url)
        self.assertEqual(resp.status_code, 403)

    def test_status_missing_record(self):
        """
        Attempting to get the status of an export task which isn't currently
        represented in the database should yield a useful result
        """
        resp = self.client.get(self.status_url)
        self.assertEqual(resp.status_code, 200)
        result = json.loads(resp.content)
        self.assertEqual(result['ExportStatus'], 0)

    def test_output_non_course_author(self):
        """
        Verify that users who aren't authors of the course are unable to see the output of export tasks
        """
        client, _ = self.create_non_staff_authed_user_client()
        resp = client.get(reverse_course_url('export_output_handler', self.course.id))
        self.assertEqual(resp.status_code, 403)


@override_settings(CONTENTSTORE=TEST_DATA_CONTENTSTORE)
class TestLibraryImportExport(CourseTestCase):
    """
    Tests for importing content libraries from XML and exporting them to XML.
    """
    def setUp(self):
        super(TestLibraryImportExport, self).setUp()
        self.export_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.export_dir, ignore_errors=True)

    def test_content_library_export_import(self):
        library1 = LibraryFactory.create(modulestore=self.store)
        source_library1_key = library1.location.library_key
        library2 = LibraryFactory.create(modulestore=self.store)
        source_library2_key = library2.location.library_key

        import_library_from_xml(
            self.store,
            'test_user',
            TEST_DATA_DIR,
            ['library_empty_problem'],
            static_content_store=contentstore(),
            target_id=source_library1_key,
            load_error_modules=False,
            raise_on_failure=True,
            create_if_not_present=True,
        )

        export_library_to_xml(
            self.store,
            contentstore(),
            source_library1_key,
            self.export_dir,
            'exported_source_library',
        )

        source_library = self.store.get_library(source_library1_key)
        self.assertEqual(source_library.url_name, 'library')

        # Import the exported library into a different content library.
        import_library_from_xml(
            self.store,
            'test_user',
            self.export_dir,
            ['exported_source_library'],
            static_content_store=contentstore(),
            target_id=source_library2_key,
            load_error_modules=False,
            raise_on_failure=True,
            create_if_not_present=True,
        )

        # Compare the two content libraries for equality.
        self.assertCoursesEqual(source_library1_key, source_library2_key)


@ddt.ddt
@override_settings(CONTENTSTORE=TEST_DATA_CONTENTSTORE)
class TestCourseExportImport(LibraryTestCase):
    """
    Tests for importing after exporting the course containing content libraries from XML.
    """
    def setUp(self):
        super(TestCourseExportImport, self).setUp()
        self.export_dir = tempfile.mkdtemp()

        # Create a problem in library
        ItemFactory.create(
            category="problem",
            parent_location=self.library.location,
            user_id=self.user.id,   # pylint: disable=no-member
            publish_item=False,
            display_name='Test Problem',
            data="<problem><multiplechoiceresponse></multiplechoiceresponse></problem>",
        )

        # Create a source course.
        self.source_course = CourseFactory.create(default_store=ModuleStoreEnum.Type.split)
        self.addCleanup(shutil.rmtree, self.export_dir, ignore_errors=True)

    def _setup_source_course_with_library_content(self, publish=False):
        """
        Sets up course with library content.
        """
        chapter = ItemFactory.create(
            parent_location=self.source_course.location,
            category='chapter',
            display_name='Test Section'
        )
        sequential = ItemFactory.create(
            parent_location=chapter.location,
            category='sequential',
            display_name='Test Sequential'
        )
        vertical = ItemFactory.create(
            category='vertical',
            parent_location=sequential.location,
            display_name='Test Unit'
        )
        lc_block = self._add_library_content_block(vertical, self.lib_key, publish_item=publish)
        self._refresh_children(lc_block)

    def get_lib_content_block_children(self, block_location):
        """
        Search for library content block to return its immediate children
        """
        if block_location.block_type == 'library_content':
            return self.store.get_item(block_location).children

        return self.get_lib_content_block_children(self.store.get_item(block_location).children[0])

    def assert_problem_display_names(self, source_course_location, dest_course_location, is_published):
        """
        Asserts that problems' display names in both source and destination courses are same.
        """
        source_course_lib_children = self.get_lib_content_block_children(source_course_location)
        dest_course_lib_children = self.get_lib_content_block_children(dest_course_location)

        self.assertEquals(len(source_course_lib_children), len(dest_course_lib_children))

        for source_child_location, dest_child_location in zip(source_course_lib_children, dest_course_lib_children):
            # Assert problem names on draft branch.
            with self.store.branch_setting(branch_setting=ModuleStoreEnum.Branch.draft_preferred):
                self.assert_names(source_child_location, dest_child_location)

            if is_published:
                # Assert problem names on publish branch.
                with self.store.branch_setting(branch_setting=ModuleStoreEnum.Branch.published_only):
                    self.assert_names(source_child_location, dest_child_location)

    def assert_names(self, source_child_location, dest_child_location):
        """
        Check if blocks have same display_name.
        """
        source_child = self.store.get_item(source_child_location)
        dest_child = self.store.get_item(dest_child_location)
        self.assertEquals(source_child.display_name, dest_child.display_name)

    @ddt.data(True, False)
    def test_library_content_on_course_export_import(self, publish_item):
        """
        Verify that library contents in destination and source courses are same after importing
        the source course into destination course.
        """
        self._setup_source_course_with_library_content(publish=publish_item)

        # Create a course to import source course.
        dest_course = CourseFactory.create(default_store=ModuleStoreEnum.Type.split)

        # Export the source course.
        export_course_to_xml(
            self.store,
            contentstore(),
            self.source_course.location.course_key,
            self.export_dir,
            'exported_source_course',
        )

        # Now, import it back to dest_course.
        import_course_from_xml(
            self.store,
            self.user.id,   # pylint: disable=no-member
            self.export_dir,
            ['exported_source_course'],
            static_content_store=contentstore(),
            target_id=dest_course.location.course_key,
            load_error_modules=False,
            raise_on_failure=True,
            create_if_not_present=True,
        )

        self.assert_problem_display_names(
            self.source_course.location,
            dest_course.location,
            publish_item
        )
