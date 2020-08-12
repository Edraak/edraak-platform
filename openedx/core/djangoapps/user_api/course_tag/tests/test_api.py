"""
Test the user course tag API.
"""
from django.test import TestCase

from student.tests.factories import UserFactory
from openedx.core.djangoapps.user_api.course_tag import api as course_tag_api
from opaque_keys.edx.locator import CourseLocator


class TestCourseTagAPI(TestCase):
    """
    Test the user service
    """
    shard = 2

    def setUp(self):
        super(TestCourseTagAPI, self).setUp()
        self.user = UserFactory.create()
        self.course_id = CourseLocator('test_org', 'test_course_number', 'test_run')
        self.test_key = 'test_key'

    def test_get_set_course_tag(self):
        # get a tag that doesn't exist
        tag = course_tag_api.get_course_tag(self.user, self.course_id, self.test_key)
        self.assertIsNone(tag)

        # test setting a new key
        test_value = 'value'
        course_tag_api.set_course_tag(self.user, self.course_id, self.test_key, test_value)
        tag = course_tag_api.get_course_tag(self.user, self.course_id, self.test_key)
        self.assertEqual(tag, test_value)

        #test overwriting an existing key
        test_value = 'value2'
        course_tag_api.set_course_tag(self.user, self.course_id, self.test_key, test_value)
        tag = course_tag_api.get_course_tag(self.user, self.course_id, self.test_key)
        self.assertEqual(tag, test_value)
