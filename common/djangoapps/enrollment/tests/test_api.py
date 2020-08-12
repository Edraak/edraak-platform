"""
Tests for student enrollment.
"""
import unittest

import ddt
import pytest
from django.conf import settings
from django.test.utils import override_settings
from mock import Mock, patch

from course_modes.models import CourseMode
from enrollment import api
from enrollment.errors import CourseModeNotFoundError, EnrollmentApiLoadError, EnrollmentNotFoundError
from enrollment.tests import fake_data_api
from openedx.core.djangolib.testing.utils import CacheIsolationTestCase


@ddt.ddt
@override_settings(ENROLLMENT_DATA_API="enrollment.tests.fake_data_api")
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class EnrollmentTest(CacheIsolationTestCase):
    """
    Test student enrollment, especially with different course modes.
    """
    USERNAME = "Bob"
    COURSE_ID = "some/great/course"

    ENABLED_CACHES = ['default']

    def setUp(self):
        super(EnrollmentTest, self).setUp()
        fake_data_api.reset()

    @ddt.data(
        # Default (no course modes in the database)
        # Expect automatically being enrolled as "honor".
        ([], 'honor'),

        # Audit / Verified / Honor
        # We should always go to the "choose your course" page.
        # We should also be enrolled as "honor" by default.
        (['honor', 'verified', 'audit'], 'honor'),

        # Check for professional ed happy path.
        (['professional'], 'professional'),
        (['no-id-professional'], 'no-id-professional')
    )
    @ddt.unpack
    def test_enroll(self, course_modes, mode):
        # Add a fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=course_modes)
        # Enroll in the course and verify the URL we get sent to
        result = api.add_enrollment(self.USERNAME, self.COURSE_ID, mode=mode)
        self.assertIsNotNone(result)
        self.assertEquals(result['student'], self.USERNAME)
        self.assertEquals(result['course']['course_id'], self.COURSE_ID)
        self.assertEquals(result['mode'], mode)

        get_result = api.get_enrollment(self.USERNAME, self.COURSE_ID)
        self.assertEquals(result, get_result)

    @ddt.data(
        ([CourseMode.DEFAULT_MODE_SLUG, 'verified', 'credit'], CourseMode.DEFAULT_MODE_SLUG),
        (['audit', 'verified', 'credit'], 'audit'),
        (['honor', 'verified', 'credit'], 'honor'),
    )
    @ddt.unpack
    def test_enroll_no_mode_success(self, course_modes, expected_mode):
        # Add a fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=course_modes)
        with patch('enrollment.api.CourseMode.modes_for_course') as mock_modes_for_course:
            mock_course_modes = [Mock(slug=mode) for mode in course_modes]
            mock_modes_for_course.return_value = mock_course_modes
            # Enroll in the course and verify the URL we get sent to
            result = api.add_enrollment(self.USERNAME, self.COURSE_ID)
            self.assertIsNotNone(result)
            self.assertEquals(result['student'], self.USERNAME)
            self.assertEquals(result['course']['course_id'], self.COURSE_ID)
            self.assertEquals(result['mode'], expected_mode)

    @ddt.data(
        ['professional'],
        ['verified'],
        ['verified', 'professional'],
    )
    def test_enroll_no_mode_error(self, course_modes):
        # Add a fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=course_modes)
        # Enroll in the course and verify that we raise CourseModeNotFoundError
        with pytest.raises(CourseModeNotFoundError):
            api.add_enrollment(self.USERNAME, self.COURSE_ID)

    def test_prof_ed_enroll(self):
        # Add a fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=['professional'])
        # Enroll in the course and verify the URL we get sent to
        with pytest.raises(CourseModeNotFoundError):
            api.add_enrollment(self.USERNAME, self.COURSE_ID, mode='verified')

    @ddt.data(
        # Default (no course modes in the database)
        # Expect that users are automatically enrolled as "honor".
        ([], 'honor'),

        # Audit / Verified / Honor
        # We should always go to the "choose your course" page.
        # We should also be enrolled as "honor" by default.
        (['honor', 'verified', 'audit'], 'honor'),

        # Check for professional ed happy path.
        (['professional'], 'professional'),
        (['no-id-professional'], 'no-id-professional')
    )
    @ddt.unpack
    def test_unenroll(self, course_modes, mode):
        # Add a fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=course_modes)
        # Enroll in the course and verify the URL we get sent to
        result = api.add_enrollment(self.USERNAME, self.COURSE_ID, mode=mode)
        self.assertIsNotNone(result)
        self.assertEquals(result['student'], self.USERNAME)
        self.assertEquals(result['course']['course_id'], self.COURSE_ID)
        self.assertEquals(result['mode'], mode)
        self.assertTrue(result['is_active'])

        result = api.update_enrollment(self.USERNAME, self.COURSE_ID, mode=mode, is_active=False)
        self.assertIsNotNone(result)
        self.assertEquals(result['student'], self.USERNAME)
        self.assertEquals(result['course']['course_id'], self.COURSE_ID)
        self.assertEquals(result['mode'], mode)
        self.assertFalse(result['is_active'])

    def test_unenroll_not_enrolled_in_course(self):
        # Add a fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=['honor'])
        with pytest.raises(EnrollmentNotFoundError):
            api.update_enrollment(self.USERNAME, self.COURSE_ID, mode='honor', is_active=False)

    @ddt.data(
        # Simple test of honor and verified.
        ([
            {'course_id': 'the/first/course', 'course_modes': [], 'mode': 'honor'},
            {'course_id': 'the/second/course', 'course_modes': ['honor', 'verified'], 'mode': 'verified'}
        ]),

        # No enrollments
        ([]),

        # One Enrollment
        ([
            {'course_id': 'the/third/course', 'course_modes': ['honor', 'verified', 'audit'], 'mode': 'audit'}
        ]),
    )
    def test_get_all_enrollments(self, enrollments):
        for enrollment in enrollments:
            fake_data_api.add_course(enrollment['course_id'], course_modes=enrollment['course_modes'])
            api.add_enrollment(self.USERNAME, enrollment['course_id'], enrollment['mode'])
        result = api.get_enrollments(self.USERNAME)
        self.assertEqual(len(enrollments), len(result))
        for result_enrollment in result:
            self.assertIn(
                result_enrollment['course']['course_id'],
                [enrollment['course_id'] for enrollment in enrollments]
            )

    def test_update_enrollment(self):
        # Add fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=['honor', 'verified', 'audit'])
        # Enroll in the course and verify the URL we get sent to
        result = api.add_enrollment(self.USERNAME, self.COURSE_ID, mode='audit')
        get_result = api.get_enrollment(self.USERNAME, self.COURSE_ID)
        self.assertEquals(result, get_result)

        result = api.update_enrollment(self.USERNAME, self.COURSE_ID, mode='honor')
        self.assertEquals('honor', result['mode'])

        result = api.update_enrollment(self.USERNAME, self.COURSE_ID, mode='verified')
        self.assertEquals('verified', result['mode'])

    def test_update_enrollment_attributes(self):
        # Add fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=['honor', 'verified', 'audit', 'credit'])
        # Enroll in the course and verify the URL we get sent to
        result = api.add_enrollment(self.USERNAME, self.COURSE_ID, mode='audit')
        get_result = api.get_enrollment(self.USERNAME, self.COURSE_ID)
        self.assertEquals(result, get_result)

        enrollment_attributes = [
            {
                "namespace": "credit",
                "name": "provider_id",
                "value": "hogwarts",
            }
        ]

        result = api.update_enrollment(
            self.USERNAME, self.COURSE_ID, mode='credit', enrollment_attributes=enrollment_attributes
        )
        self.assertEquals('credit', result['mode'])
        attributes = api.get_enrollment_attributes(self.USERNAME, self.COURSE_ID)
        self.assertEquals(enrollment_attributes[0], attributes[0])

    def test_get_course_details(self):
        # Add a fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=['honor', 'verified', 'audit'])
        result = api.get_course_enrollment_details(self.COURSE_ID)
        self.assertEquals(result['course_id'], self.COURSE_ID)
        self.assertEquals(3, len(result['course_modes']))

    @override_settings(ENROLLMENT_DATA_API='foo.bar.biz.baz')
    def test_data_api_config_error(self):
        # Enroll in the course and verify the URL we get sent to
        with pytest.raises(EnrollmentApiLoadError):
            api.add_enrollment(self.USERNAME, self.COURSE_ID, mode='audit')

    def test_caching(self):
        # Add fake course enrollment information to the fake data API
        fake_data_api.add_course(self.COURSE_ID, course_modes=['honor', 'verified', 'audit'])

        # Hit the fake data API.
        details = api.get_course_enrollment_details(self.COURSE_ID)

        # Reset the fake data API, should rely on the cache.
        fake_data_api.reset()
        cached_details = api.get_course_enrollment_details(self.COURSE_ID)

        # The data matches
        self.assertEqual(len(details['course_modes']), 3)
        self.assertEqual(details, cached_details)

    def test_update_enrollment_expired_mode_with_error(self):
        """ Verify that if verified mode is expired and include expire flag is
        false then enrollment cannot be updated. """
        self.assert_add_modes_with_enrollment('audit')
        # On updating enrollment mode to verified it should the raise the error.
        with self.assertRaises(CourseModeNotFoundError):
            self.assert_update_enrollment(mode='verified', include_expired=False)

    def test_update_enrollment_with_expired_mode(self):
        """ Verify that if verified mode is expired then enrollment can be
        updated if include_expired flag is true."""
        self.assert_add_modes_with_enrollment('audit')
        # enrollment in verified mode will work fine with include_expired=True
        self.assert_update_enrollment(mode='verified', include_expired=True)

    @ddt.data(True, False)
    def test_unenroll_with_expired_mode(self, include_expired):
        """ Verify that un-enroll will work fine for expired courses whether include_expired
        is true or false."""
        self.assert_add_modes_with_enrollment('verified')
        self.assert_update_enrollment(mode='verified', is_active=False, include_expired=include_expired)

    def assert_add_modes_with_enrollment(self, enrollment_mode):
        """ Dry method for adding fake course enrollment information to fake
        data API and enroll the student in the course. """
        fake_data_api.add_course(self.COURSE_ID, course_modes=['honor', 'verified', 'audit'])
        result = api.add_enrollment(self.USERNAME, self.COURSE_ID, mode=enrollment_mode)
        get_result = api.get_enrollment(self.USERNAME, self.COURSE_ID)
        self.assertEquals(result, get_result)
        # set the course verify mode as expire.
        fake_data_api.set_expired_mode(self.COURSE_ID)

    def assert_update_enrollment(self, mode, is_active=True, include_expired=False):
        """ Dry method for updating enrollment."""

        result = api.update_enrollment(
            self.USERNAME, self.COURSE_ID, mode=mode, is_active=is_active, include_expired=include_expired
        )
        self.assertEquals(mode, result['mode'])
        self.assertIsNotNone(result)
        self.assertEquals(result['student'], self.USERNAME)
        self.assertEquals(result['course']['course_id'], self.COURSE_ID)
        self.assertEquals(result['mode'], mode)

        if is_active:
            self.assertTrue(result['is_active'])
        else:
            self.assertFalse(result['is_active'])
