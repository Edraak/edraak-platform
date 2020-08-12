"""
Tests that check that we ignore the appropriate files when importing courses.
"""
import unittest
from mock import Mock

from xmodule.modulestore.xml_importer import StaticContentImporter
from opaque_keys.edx.locator import CourseLocator
from xmodule.tests import DATA_DIR
from xmodule.modulestore.tests.utils import (
    add_temp_files_from_dict, remove_temp_files_from_list, DOT_FILES_DICT, TILDA_FILES_DICT
)


class IgnoredFilesTestCase(unittest.TestCase):
    "Tests for ignored files"
    shard = 1
    course_dir = DATA_DIR / "course_ignore"
    dict_list = [DOT_FILES_DICT, TILDA_FILES_DICT]

    def setUp(self):
        super(IgnoredFilesTestCase, self).setUp()
        for dictionary in self.dict_list:
            self.addCleanup(remove_temp_files_from_list, dictionary.keys(), self.course_dir / "static")
            add_temp_files_from_dict(dictionary, self.course_dir / "static")

    def test_sample_static_files(self):
        """
        Test for to ensure Mac OS metadata files (filename starts with "._") as well
        as files ending with "~" get ignored, while files starting with "." are not.
        """
        course_id = CourseLocator("edX", "course_ignore", "2014_Fall")
        content_store = Mock()
        content_store.generate_thumbnail.return_value = ("content", "location")
        static_content_importer = StaticContentImporter(
            static_content_store=content_store,
            course_data_path=self.course_dir,
            target_id=course_id
        )
        static_content_importer.import_static_content_directory()
        saved_static_content = [call[0][0] for call in content_store.save.call_args_list]
        name_val = {sc.name: sc.data for sc in saved_static_content}
        self.assertIn("example.txt", name_val)
        self.assertIn(".example.txt", name_val)
        self.assertIn("GREEN", name_val["example.txt"])
        self.assertIn("BLUE", name_val[".example.txt"])
        self.assertNotIn("._example.txt", name_val)
        self.assertNotIn(".DS_Store", name_val)
        self.assertNotIn("example.txt~", name_val)
