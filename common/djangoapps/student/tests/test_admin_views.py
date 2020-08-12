"""
Tests student admin.py
"""
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.urls import reverse
from django.test import TestCase
from mock import Mock

from student.admin import UserAdmin
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory


class AdminCourseRolesPageTest(SharedModuleStoreTestCase):
    """Test the django admin course roles form saving data in db.
    """
    @classmethod
    def setUpClass(cls):
        super(AdminCourseRolesPageTest, cls).setUpClass()
        cls.course = CourseFactory.create(org='edx')

    def setUp(self):
        super(AdminCourseRolesPageTest, self).setUp()
        self.user = UserFactory.create(is_staff=True, is_superuser=True)
        self.user.save()

    def test_save_valid_data(self):

        data = {
            'course_id': unicode(self.course.id),
            'role': 'finance_admin',
            'org': 'edx',
            'email': self.user.email
        }

        self.client.login(username=self.user.username, password='test')

        # # adding new role from django admin page
        response = self.client.post(reverse('admin:student_courseaccessrole_add'), data=data)
        self.assertRedirects(response, reverse('admin:student_courseaccessrole_changelist'))

        response = self.client.get(reverse('admin:student_courseaccessrole_changelist'))
        self.assertContains(response, 'Select course access role to change')
        self.assertContains(response, 'Add course access role')
        self.assertContains(response, 'finance_admin')
        self.assertContains(response, unicode(self.course.id))
        self.assertContains(response, '1 course access role')

        #try adding with same information raise error.
        response = self.client.post(reverse('admin:student_courseaccessrole_add'), data=data)
        self.assertContains(response, 'Duplicate')

    def test_save_without_org_and_course_data(self):

        data = {
            'role': 'staff',
            'email': self.user.email,
            'course_id': unicode(self.course.id)
        }

        self.client.login(username=self.user.username, password='test')

        # # adding new role from django admin page
        response = self.client.post(reverse('admin:student_courseaccessrole_add'), data=data)
        self.assertRedirects(response, reverse('admin:student_courseaccessrole_changelist'))

        response = self.client.get(reverse('admin:student_courseaccessrole_changelist'))
        self.assertContains(response, 'staff')
        self.assertContains(response, '1 course access role')

    def test_save_with_course_only(self):

        data = {
            'role': 'beta_testers',
            'email': self.user.email,

        }

        self.client.login(username=self.user.username, password='test')

        # # adding new role from django admin page
        response = self.client.post(reverse('admin:student_courseaccessrole_add'), data=data)
        self.assertRedirects(response, reverse('admin:student_courseaccessrole_changelist'))

        response = self.client.get(reverse('admin:student_courseaccessrole_changelist'))
        self.assertContains(response, 'beta_testers')
        self.assertContains(response, '1 course access role')

    def test_save_with_org_only(self):

        data = {
            'role': 'beta_testers',
            'email': self.user.email,
            'org': 'myorg'

        }

        self.client.login(username=self.user.username, password='test')

        # # adding new role from django admin page
        response = self.client.post(reverse('admin:student_courseaccessrole_add'), data=data)
        self.assertRedirects(response, reverse('admin:student_courseaccessrole_changelist'))

        response = self.client.get(reverse('admin:student_courseaccessrole_changelist'))
        self.assertContains(response, 'myorg')
        self.assertContains(response, '1 course access role')

    def test_save_with_invalid_course(self):

        course = unicode('no/edx/course')
        email = "invalid@email.com"
        data = {
            'course_id': course,
            'role': 'finance_admin',
            'org': 'edx',
            'email': email
        }

        self.client.login(username=self.user.username, password='test')

        # Adding new role with invalid data
        response = self.client.post(reverse('admin:student_courseaccessrole_add'), data=data)
        self.assertContains(
            response,
            'Course not found. Entered course id was: &quot;{}&quot;.'.format(
                course
            )
        )

        self.assertContains(
            response,
            "Email does not exist. Could not find {}. Please re-enter email address".format(
                email
            )
        )

    def test_save_valid_course_invalid_org(self):

        data = {
            'course_id': unicode(self.course.id),
            'role': 'finance_admin',
            'org': 'edxxx',
            'email': self.user.email
        }

        self.client.login(username=self.user.username, password='test')

        # # adding new role from django admin page
        response = self.client.post(reverse('admin:student_courseaccessrole_add'), data=data)
        self.assertContains(
            response,
            'Org name {} is not valid. Valid name is {}.'.format(
                'edxxx', 'edx'
            )
        )


class AdminUserPageTest(TestCase):
    """
    Unit tests for the UserAdmin view.
    """
    def setUp(self):
        super(AdminUserPageTest, self).setUp()
        self.admin = UserAdmin(User, AdminSite())

    def test_username_is_writable_for_user_creation(self):
        """
        Ensures that the username is not readonly, when admin creates new user.
        """
        request = Mock()
        self.assertNotIn('username', self.admin.get_readonly_fields(request))

    def test_username_is_readonly_for_user(self):
        """
        Ensures that the username field is readonly, when admin open user which already exists.

        This hook used for skip Django validation in the `auth_user_change` view.

        Changing the username is still possible using the database or from the model directly.

        However, changing the username might cause issues with the logs and/or the cs_comments_service since it
        stores the username in a different database.
        """
        request = Mock()
        user = Mock()
        self.assertIn('username', self.admin.get_readonly_fields(request, user))
