""" Unit tests for custom UserProfile properties. """

from __future__ import absolute_import, division, print_function, unicode_literals

import ddt
from django.test import TestCase
from django.test.utils import override_settings

from completion import models
from completion.test_utils import CompletionWaffleTestMixin
from openedx.core.djangoapps.user_api.accounts.utils import retrieve_last_sitewide_block_completed
from openedx.core.djangolib.testing.utils import skip_unless_lms
from student.models import CourseEnrollment
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

from ..utils import format_social_link, validate_social_link, generate_password


@ddt.ddt
class UserAccountSettingsTest(TestCase):
    """Unit tests for setting Social Media Links."""

    def setUp(self):
        super(UserAccountSettingsTest, self).setUp()

    def validate_social_link(self, social_platform, link):
        """
        Helper method that returns True if the social link is valid, False if
        the input link fails validation and will throw an error.
        """
        try:
            validate_social_link(social_platform, link)
        except ValueError:
            return False
        return True

    @ddt.data(
        ('facebook', 'www.facebook.com/edX', 'https://www.facebook.com/edX', True),
        ('facebook', 'facebook.com/edX/', 'https://www.facebook.com/edX', True),
        ('facebook', 'HTTP://facebook.com/edX/', 'https://www.facebook.com/edX', True),
        ('facebook', 'www.evilwebsite.com/123', None, False),
        ('twitter', 'https://www.twiter.com/edX/', None, False),
        ('twitter', 'https://www.twitter.com/edX/123s', None, False),
        ('twitter', 'twitter.com/edX', 'https://www.twitter.com/edX', True),
        ('twitter', 'twitter.com/edX?foo=bar', 'https://www.twitter.com/edX', True),
        ('twitter', 'twitter.com/test.user', 'https://www.twitter.com/test.user', True),
        ('linkedin', 'www.linkedin.com/harryrein', None, False),
        ('linkedin', 'www.linkedin.com/in/harryrein-1234', 'https://www.linkedin.com/in/harryrein-1234', True),
        ('linkedin', 'www.evilwebsite.com/123?www.linkedin.com/edX', None, False),
        ('linkedin', '', '', True),
        ('linkedin', None, None, False),
    )
    @ddt.unpack
    @skip_unless_lms
    def test_social_link_input(self, platform_name, link_input, formatted_link_expected, is_valid_expected):
        """
        Verify that social links are correctly validated and formatted.
        """
        self.assertEqual(is_valid_expected, self.validate_social_link(platform_name, link_input))

        self.assertEqual(formatted_link_expected, format_social_link(platform_name, link_input))


@ddt.ddt
class CompletionUtilsTestCase(SharedModuleStoreTestCase, CompletionWaffleTestMixin, TestCase):
    """
    Test completion utility functions
    """
    def setUp(self):
        """
        Creates a test course that can be used for non-destructive tests
        """
        super(CompletionUtilsTestCase, self).setUp()
        self.override_waffle_switch(True)
        self.engaged_user = UserFactory.create()
        self.cruft_user = UserFactory.create()
        self.course = self.create_test_course()
        self.submit_faux_completions()

    def create_test_course(self):
        """
        Create, populate test course.
        """
        course = CourseFactory.create()
        with self.store.bulk_operations(course.id):
            self.chapter = ItemFactory.create(category='chapter', parent_location=course.location)
            self.sequential = ItemFactory.create(category='sequential', parent_location=self.chapter.location)
            self.vertical1 = ItemFactory.create(category='vertical', parent_location=self.sequential.location)
            self.vertical2 = ItemFactory.create(category='vertical', parent_location=self.sequential.location)
        course.children = [self.chapter]
        self.chapter.children = [self.sequential]
        self.sequential.children = [self.vertical1, self.vertical2]

        if hasattr(self, 'user_one'):
            CourseEnrollment.enroll(self.engaged_user, course.id)
        if hasattr(self, 'user_two'):
            CourseEnrollment.enroll(self.cruft_user, course.id)
        return course

    def submit_faux_completions(self):
        """
        Submit completions (only for user_one)g
        """
        for block in self.course.children[0].children[0].children:
            models.BlockCompletion.objects.submit_completion(
                user=self.engaged_user,
                course_key=self.course.id,
                block_key=block.location,
                completion=1.0
            )

    @override_settings(LMS_ROOT_URL='test_url:9999')
    def test_retrieve_last_sitewide_block_completed(self):
        """
        Test that the method returns a URL for the "last completed" block
        when sending a user object
        """
        block_url = retrieve_last_sitewide_block_completed(
            self.engaged_user
        )
        empty_block_url = retrieve_last_sitewide_block_completed(
            self.cruft_user
        )
        self.assertEqual(
            block_url,
            u'test_url:9999/courses/{org}/{course}/{run}/jump_to/i4x://{org}/{course}/vertical/{vertical_id}'.format(
                org=self.course.location.course_key.org,
                course=self.course.location.course_key.course,
                run=self.course.location.course_key.run,
                vertical_id=self.vertical2.location.block_id,
            )
        )
        self.assertEqual(empty_block_url, None)


class GeneratePasswordTest(TestCase):
    """Tests formation of randomly generated passwords."""

    def test_default_args(self):
        password = generate_password()
        self.assertEqual(12, len(password))
        self.assertTrue(any(c.isdigit for c in password))
        self.assertTrue(any(c.isalpha for c in password))

    def test_length(self):
        length = 25
        self.assertEqual(length, len(generate_password(length=length)))

    def test_chars(self):
        char = '!'
        password = generate_password(length=12, chars=(char,))

        self.assertTrue(any(c.isdigit for c in password))
        self.assertTrue(any(c.isalpha for c in password))
        self.assertEqual(char * 10, password[2:])

    def test_min_length(self):
        with self.assertRaises(ValueError):
            generate_password(length=7)
