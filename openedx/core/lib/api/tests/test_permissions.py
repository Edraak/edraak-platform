""" Tests for API permissions classes. """

import ddt
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import TestCase, RequestFactory
from rest_framework.generics import GenericAPIView

from student.roles import CourseStaffRole, CourseInstructorRole
from openedx.core.lib.api.permissions import (
    IsStaffOrOwner,
    IsCourseStaffInstructor,
    IsMasterCourseStaffInstructor,
)
from student.tests.factories import UserFactory
from opaque_keys.edx.keys import CourseKey


class TestObject(object):
    """ Fake class for object permission tests. """
    def __init__(self, user=None, course_id=None):
        self.user = user
        self.course_id = course_id


class TestCcxObject(TestObject):
    """ Fake class for object permission for CCX Courses """
    def __init__(self, user=None, course_id=None):
        super(TestCcxObject, self).__init__(user, course_id)
        self.coach = user


class IsCourseStaffInstructorTests(TestCase):
    """ Test for IsCourseStaffInstructor permission class. """
    shard = 2

    def setUp(self):
        super(IsCourseStaffInstructorTests, self).setUp()
        self.permission = IsCourseStaffInstructor()
        self.coach = UserFactory()
        self.user = UserFactory()
        self.request = RequestFactory().get('/')
        self.request.user = self.user
        self.course_key = CourseKey.from_string('edx/test123/run')
        self.obj = TestCcxObject(user=self.coach, course_id=self.course_key)

    def test_course_staff_has_access(self):
        CourseStaffRole(course_key=self.course_key).add_users(self.user)
        self.assertTrue(self.permission.has_object_permission(self.request, None, self.obj))

    def test_course_instructor_has_access(self):
        CourseInstructorRole(course_key=self.course_key).add_users(self.user)
        self.assertTrue(self.permission.has_object_permission(self.request, None, self.obj))

    def test_course_coach_has_access(self):
        self.request.user = self.coach
        self.assertTrue(self.permission.has_object_permission(self.request, None, self.obj))

    def test_any_user_has_no_access(self):
        self.assertFalse(self.permission.has_object_permission(self.request, None, self.obj))

    def test_anonymous_has_no_access(self):
        self.request.user = AnonymousUser()
        self.assertFalse(self.permission.has_object_permission(self.request, None, self.obj))


class IsMasterCourseStaffInstructorTests(TestCase):
    """ Test for IsMasterCourseStaffInstructorTests permission class. """
    shard = 2

    def setUp(self):
        super(IsMasterCourseStaffInstructorTests, self).setUp()
        self.permission = IsMasterCourseStaffInstructor()
        master_course_id = 'edx/test123/run'
        self.user = UserFactory()
        self.get_request = RequestFactory().get('/?master_course_id={}'.format(master_course_id))
        self.get_request.user = self.user
        self.post_request = RequestFactory().post('/', data={'master_course_id': master_course_id})
        self.post_request.user = self.user
        self.course_key = CourseKey.from_string(master_course_id)

    def test_course_staff_has_access(self):
        CourseStaffRole(course_key=self.course_key).add_users(self.user)
        self.assertTrue(self.permission.has_permission(self.get_request, None))
        self.assertTrue(self.permission.has_permission(self.post_request, None))

    def test_course_instructor_has_access(self):
        CourseInstructorRole(course_key=self.course_key).add_users(self.user)
        self.assertTrue(self.permission.has_permission(self.get_request, None))
        self.assertTrue(self.permission.has_permission(self.post_request, None))

    def test_any_user_has_partial_access(self):
        self.assertFalse(self.permission.has_permission(self.get_request, None))
        self.assertFalse(self.permission.has_permission(self.post_request, None))

    def test_anonymous_has_no_access(self):
        user = AnonymousUser()
        self.get_request.user = user
        self.post_request.user = user
        self.assertFalse(self.permission.has_permission(self.get_request, None))
        self.assertFalse(self.permission.has_permission(self.post_request, None))

    def test_wrong_course_id_raises(self):
        get_request = RequestFactory().get('/?master_course_id=this_is_invalid')
        with self.assertRaises(Http404):
            self.permission.has_permission(get_request, None)
        post_request = RequestFactory().post('/', data={'master_course_id': 'this_is_invalid'})
        with self.assertRaises(Http404):
            self.permission.has_permission(post_request, None)


@ddt.ddt
class IsStaffOrOwnerTests(TestCase):
    """ Tests for IsStaffOrOwner permission class. """
    shard = 2

    def setUp(self):
        super(IsStaffOrOwnerTests, self).setUp()
        self.permission = IsStaffOrOwner()
        self.request = RequestFactory().get('/')
        self.obj = TestObject()

    def assert_user_has_object_permission(self, user, permitted):
        """
        Asserts whether or not the user has permission to access an object.

        Arguments
            user (User)
            permitted (boolean)
        """
        self.request.user = user
        self.assertEqual(self.permission.has_object_permission(self.request, None, self.obj), permitted)

    def test_staff_user(self):
        """ Staff users should be permitted. """
        user = UserFactory(is_staff=True)
        self.assert_user_has_object_permission(user, True)

    def test_owner(self):
        """ Owners should be permitted. """
        user = UserFactory()
        self.obj.user = user
        self.assert_user_has_object_permission(user, True)

    def test_non_staff_test_non_owner_or_staff_user(self):
        """ Non-staff and non-owner users should not be permitted. """
        user = UserFactory()
        self.assert_user_has_object_permission(user, False)

    def test_has_permission_as_staff(self):
        """ Staff users always have permission. """
        self.request.user = UserFactory(is_staff=True)
        self.assertTrue(self.permission.has_permission(self.request, None))

    def test_has_permission_as_owner_with_get(self):
        """ Owners always have permission to make GET actions. """
        user = UserFactory()
        request = RequestFactory().get('/?username={}'.format(user.username))
        request.user = user
        self.assertTrue(self.permission.has_permission(request, None))

    def test_has_permission_with_view_kwargs_as_owner_with_get(self):
        """ Owners always have permission to make GET actions. """
        user = UserFactory()
        self.request.user = user
        view = GenericAPIView()
        view.kwargs = {'username': user.username}
        self.assertTrue(self.permission.has_permission(self.request, view))

    @ddt.data('patch', 'post', 'put')
    def test_has_permission_as_owner_with_edit(self, action):
        """ Owners always have permission to edit. """
        user = UserFactory()

        data = {'username': user.username}
        request = getattr(RequestFactory(), action)('/', data, format='json')
        request.user = user
        request.data = data  # Note (CCB): This is a hack that should be fixed. (ECOM-3171)
        self.assertTrue(self.permission.has_permission(request, None))

    def test_has_permission_as_non_owner(self):
        """ Non-owners should not have permission. """
        user = UserFactory()
        request = RequestFactory().get('/?username={}'.format(user.username))
        request.user = UserFactory()
        self.assertFalse(self.permission.has_permission(request, None))

    def test_has_permission_with_view_kwargs_as_non_owner(self):
        """ Non-owners should not have permission. """
        user = UserFactory()
        self.request.user = user
        view = GenericAPIView()
        view.kwargs = {'username': UserFactory().username}
        self.assertFalse(self.permission.has_permission(self.request, view))
