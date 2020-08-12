"""
Tests for v1 views
"""
from __future__ import unicode_literals
from collections import OrderedDict

import ddt
from django.urls import reverse
from mock import MagicMock, patch
from opaque_keys import InvalidKeyError
from rest_framework import status
from rest_framework.test import APITestCase

from lms.djangoapps.grades.api.v1.tests.mixins import GradeViewTestMixin
from lms.djangoapps.grades.api.v1.views import CourseGradesView
from openedx.core.djangoapps.user_authn.tests.utils import AuthAndScopesTestMixin
from student.tests.factories import UserFactory


@ddt.ddt
class SingleUserGradesTests(GradeViewTestMixin, AuthAndScopesTestMixin, APITestCase):
    """
    Tests for grades related to a course and specific user
        e.g. /api/grades/v1/courses/{course_id}/?username={username}
             /api/grades/v1/courses/?course_id={course_id}&username={username}
    """
    default_scopes = CourseGradesView.required_scopes

    @classmethod
    def setUpClass(cls):
        super(SingleUserGradesTests, cls).setUpClass()
        cls.namespaced_url = 'grades_api:v1:course_grades'

    def get_url(self, username):
        """ This method is required by AuthAndScopesTestMixin. """
        base_url = reverse(
            self.namespaced_url,
            kwargs={
                'course_id': self.course_key,
            }
        )
        return "{0}?username={1}".format(base_url, username)

    def assert_success_response_for_student(self, response):
        """ This method is required by AuthAndScopesTestMixin. """
        expected_data = [{
            'username': self.student.username,
            'email': self.student.email,
            'letter_grade': None,
            'percent': 0.0,
            'course_id': str(self.course_key),
            'passed': False
        }]
        self.assertEqual(response.data, expected_data)

    def test_nonexistent_user(self):
        """
        Test that a request for a nonexistent username returns an error.
        """
        self.client.login(username=self.global_staff.username, password=self.password)
        resp = self.client.get(self.get_url('IDoNotExist'))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_self_get_grade_not_enrolled(self):
        """
        Test that a user receives an error if she requests
        her own grade in a course where she is not enrolled.
        """
        # a user not enrolled in the course cannot request her grade
        unenrolled_user = UserFactory(password=self.password)
        self.client.login(username=unenrolled_user.username, password=self.password)
        resp = self.client.get(self.get_url(unenrolled_user.username))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error_code', resp.data)
        self.assertEqual(
            resp.data['error_code'],
            'user_not_enrolled'
        )

    def test_no_grade(self):
        """
        Test the grade for a user who has not answered any test.
        """
        self.client.login(username=self.student.username, password=self.password)
        resp = self.client.get(self.get_url(self.student.username))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        expected_data = [{
            'username': self.student.username,
            'email': self.student.email,
            'course_id': str(self.course_key),
            'passed': False,
            'percent': 0.0,
            'letter_grade': None
        }]

        self.assertEqual(resp.data, expected_data)

    def test_wrong_course_key(self):
        """
        Test that a request for an invalid course key returns an error.
        """
        def mock_from_string(*args, **kwargs):  # pylint: disable=unused-argument
            """Mocked function to always raise an exception"""
            raise InvalidKeyError('foo', 'bar')

        self.client.login(username=self.student.username, password=self.password)
        with patch('opaque_keys.edx.keys.CourseKey.from_string', side_effect=mock_from_string):
            resp = self.client.get(self.get_url(self.student.username))

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error_code', resp.data)
        self.assertEqual(
            resp.data['error_code'],
            'invalid_course_key'
        )

    def test_course_does_not_exist(self):
        """
        Test that requesting a valid, nonexistent course key returns an error as expected.
        """
        self.client.login(username=self.student.username, password=self.password)
        base_url = reverse(
            self.namespaced_url,
            kwargs={
                'course_id': 'course-v1:MITx+8.MechCX+2014_T1',
            }
        )
        url = "{0}?username={1}".format(base_url, self.student.username)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error_code', resp.data)
        self.assertEqual(
            resp.data['error_code'],
            'course_does_not_exist'
        )

    @ddt.data(
        ({'letter_grade': None, 'percent': 0.4, 'passed': False}),
        ({'letter_grade': 'Pass', 'percent': 1, 'passed': True}),
    )
    def test_grade(self, grade):
        """
        Test that the user gets her grade in case she answered tests with an insufficient score.
        """
        self.client.login(username=self.student.username, password=self.password)
        with patch('lms.djangoapps.grades.course_grade_factory.CourseGradeFactory.read') as mock_grade:
            grade_fields = {
                'letter_grade': grade['letter_grade'],
                'percent': grade['percent'],
                'passed': grade['letter_grade'] is not None,

            }
            mock_grade.return_value = MagicMock(**grade_fields)
            resp = self.client.get(self.get_url(self.student.username))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        expected_data = {
            'username': self.student.username,
            'email': self.student.email,
            'course_id': str(self.course_key),
        }

        expected_data.update(grade)
        self.assertEqual(resp.data, [expected_data])


@ddt.ddt
class CourseGradesViewTest(GradeViewTestMixin, APITestCase):
    """
    Tests for grades related to all users in a course
        e.g. /api/grades/v1/courses/{course_id}/
             /api/grades/v1/courses/?course_id={course_id}
    """

    @classmethod
    def setUpClass(cls):
        super(CourseGradesViewTest, cls).setUpClass()
        cls.namespaced_url = 'grades_api:v1:course_grades'

    def get_url(self, course_key=None):
        """
        Helper function to create the url
        """
        base_url = reverse(
            self.namespaced_url,
            kwargs={
                'course_id': course_key or self.course_key,
            }
        )

        return base_url

    def test_anonymous(self):
        resp = self.client.get(self.get_url())
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_student(self):
        self.client.login(username=self.student.username, password=self.password)
        resp = self.client.get(self.get_url())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_course_does_not_exist(self):
        self.client.login(username=self.global_staff.username, password=self.password)
        resp = self.client.get(
            self.get_url(course_key='course-v1:MITx+8.MechCX+2014_T1')
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_course_no_enrollments(self):
        self.client.login(username=self.global_staff.username, password=self.password)
        resp = self.client.get(
            self.get_url(course_key=self.empty_course.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        expected_data = OrderedDict([
            ('next', None),
            ('previous', None),
            ('results', []),
        ])
        self.assertEqual(expected_data, resp.data)

    def test_staff_can_get_all_grades(self):
        self.client.login(username=self.global_staff.username, password=self.password)
        resp = self.client.get(self.get_url())

        # this should have permission to access this API endpoint
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        expected_data = OrderedDict([
            ('next', None),
            ('previous', None),
            ('results', [
                {
                    'username': self.student.username,
                    'email': self.student.email,
                    'course_id': str(self.course.id),
                    'passed': False,
                    'percent': 0.0,
                    'letter_grade': None
                },
                {
                    'username': self.other_student.username,
                    'email': self.other_student.email,
                    'course_id': str(self.course.id),
                    'passed': False,
                    'percent': 0.0,
                    'letter_grade': None
                },
            ]),
        ])

        self.assertEqual(expected_data, resp.data)
