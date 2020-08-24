"""
Helpers for the university tests (and possibly others)
"""
from django.core.urlresolvers import reverse
from django.conf import settings

from student.tests.factories import UserFactory, UserProfileFactory, CourseEnrollmentFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory


class ModuleStoreLoggedInTestCase(ModuleStoreTestCase):
    """
    A base test class to provide helpers to create user (staff or not staff) and log him in.
    """
    LOGIN_STAFF = True
    ENROLL_USER = False

    def setUp(self):
        super(ModuleStoreLoggedInTestCase, self).setUp()
        UserProfileFactory.create(user=self.user)  # Avoid missing profile errors on the `get_user_preferences` calls

        self.course = self.create_course()

        if self.LOGIN_STAFF:
            self.login_user(self.user, self.user_password)
        else:
            user, password = self.create_non_staff_user()
            self.user = user
            self.user_password = password
            self.login_user(user, password)

    def create_non_staff_user(self):
        """
        Overrides the non-staff user method.
        """
        password = 'foo'

        user = UserFactory.create(
            password=password,
            is_staff=False,
            is_active=True,
        )
        user.save()

        return user, password

    def create_course(self):
        """
        Creates the initial course for testing.

        This method is to created to enable overriding for customization from children classes.
        """
        return CourseFactory.create()

    def login_user(self, user, password):
        """
        Login and enroll user.
        """
        if settings.ROOT_URLCONF == 'cms.urls':
            self.client.post(reverse('login_post'), {'email': user.email, 'password': password})
            dashboard_res = self.client.get(reverse('home'))
            self.assertContains(
                dashboard_res,
                u'<h1 class="page-header">{} Home</h1>'.format(settings.STUDIO_SHORT_NAME),
                msg_prefix='The user should be logged in'
            )
        else:
            self.client.post(reverse('login'), {'email': user.email, 'password': password})
            dashboard_res = self.client.get(reverse('dashboard'))
            self.assertContains(dashboard_res, 'Dashboard', msg_prefix='The user should be logged in')

        if self.ENROLL_USER:
            CourseEnrollmentFactory.create(
                user=user, course_id=self.course.id
            )
