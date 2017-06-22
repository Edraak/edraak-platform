"""
Integration tests for the University ID by testing the views.
"""

from django.core.urlresolvers import reverse
from django.shortcuts import Http404

from bs4 import BeautifulSoup
from mock import Mock, patch
import ddt

from opaque_keys.edx.locator import CourseLocator
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from edraak_university import helpers
from edraak_university.mixins import CourseContextMixin

from edraak_university.tests.factories import UniversityIDFactory
from edraak_tests.tests.helpers import ModuleStoreTestCaseLoggedIn


class CourseContextMixinTest(ModuleStoreTestCase):
    """
    Tests for CourseContextMixin context_data and helper methods.
    """

    def setUp(self):
        super(CourseContextMixinTest, self).setUp()

        course = CourseFactory.create()
        user = UserFactory.create()

        # Mocks Django generic view
        base_view_mock_class = type('BaseViewMock', (object,), {
            'get_context_data': lambda _: {},
        })

        # Mocks a University ID view
        view_mock_class = type('ViewMock', (CourseContextMixin, base_view_mock_class,), {
            'kwargs': {
                'course_id': unicode(course.id)
            },
            'request': Mock(
                user=user,
            ),
        })

        self.view = view_mock_class()
        self.course = course
        self.user = user

    def test_get_course(self):
        course_key = self.view.get_course_key()
        self.assertIsInstance(course_key, CourseLocator)

        data = self.view.get_context_data()
        self.assertEquals(data['course'].id, self.course.id)

    def test_access_control(self):
        with self.assertRaises(Http404):
            # By default the user is not 'staff'
            self.view.require_staff_access()

        try:
            with patch('edraak_university.mixins.has_access', return_value=True):
                self.view.require_staff_access()
        except Http404:
            self.fail('Should not raise a 404 error for staff users.')


@ddt.ddt
class UniversityIDViewStudentTest(ModuleStoreTestCaseLoggedIn):
    """
    Integration tests for the University ID student views.
    """

    ENROLL_USER = True
    LOGIN_STAFF = False

    def setUp(self):
        super(UniversityIDViewStudentTest, self).setUp()
        self.url = reverse('edraak_university:id', args=[unicode(self.course.id)])

    def create_course(self):
        """
        Overrides `create_course` to enable university ID.
        """
        return CourseFactory.create(enable_university_id=True)

    def submit_form(self, data_overrides=None):
        """
        Submits the student university ID form and returns the response.
        """

        form_data = {
            'full_name': self.user.profile.name,
            'university_id': 'A100C50',
            'section_number': 'B',
        }

        if data_overrides:
            form_data.update(data_overrides)

        return self.client.post(self.url, data=form_data)

    def test_basic_request(self):
        res = self.client.get(self.url)
        self.assertContains(res, 'university-id-form')
        self.assertContains(res, 'class="important"', msg_prefix='No information has been posted yet!')

        soup = BeautifulSoup(res.content)
        self.assertFalse(soup.select('ul.errorlist'), msg='Initial form should not contain errors')

    @patch('edraak_university.views.update_account_settings')
    def test_submit_form(self, update_account_settings):
        self.assertFalse(helpers.has_valid_university_id(self.user, unicode(self.course.id)),
                         msg='The ID have not been submitted yet')

        self.assertFalse(update_account_settings.called, 'Should not be called before the form submit')

        res_submit = self.submit_form()

        self.assertTrue(update_account_settings.called, 'Should follow the standard edX name change function')

        self.assertTrue(helpers.has_valid_university_id(self.user, unicode(self.course.id)),
                        msg='Should have the ID in the database')

        success_url = reverse('edraak_university:id_success', args=[unicode(self.course.id)])
        self.assertRedirects(res_submit, success_url)

        res_refresh = self.client.get(self.url)

        self.assertNotContains(res_refresh, 'class="important"',
                               msg_prefix='The form has been submitted, should not contain the notice')

    def test_submit_form_incorrect_data(self):
        self.assertFalse(helpers.has_valid_university_id(self.user, unicode(self.course.id)),
                         msg='The ID have not been submitted yet')

        res = self.submit_form({
            'university_id': 'a',
        })

        self.assertFalse(helpers.has_valid_university_id(self.user, unicode(self.course.id)),
                         msg='The information was not valid, there should be no ID')

        soup = BeautifulSoup(res.content)
        errors_list_elems = soup.select('ul.errorlist')
        self.assertTrue(len(errors_list_elems), 'Error list element should be shown')
        error_messages = unicode(errors_list_elems[0].text)
        self.assertIn('student university ID you have entered is too short', error_messages)

    @ddt.data('course_root', 'info', 'about_course', 'courseware')
    def test_view_course_pages_with_no_id(self, view_name):
        course_url = reverse(view_name, args=[unicode(self.course.id)])
        university_id_url = reverse('edraak_university:id', args=[unicode(self.course.id)])

        self.assertRedirects(self.client.get(course_url), university_id_url,
                             msg_prefix='Should not allow access to {} before having a university ID'.format(view_name))

        self.submit_form()

        self.assertContains(self.client.get(course_url), 'Skip to main',
                            msg_prefix='Should allow access to {} after entering valid university ID'.format(view_name))

    @ddt.unpack
    @ddt.data(
        {'view_name': 'edraak_university:id_list', 'view_args': []},
        {'view_name': 'edraak_university:id_update', 'view_args': ['123']},
        {'view_name': 'edraak_university:id_delete', 'view_args': ['123']},
    )
    def test_no_access_for_guests_and_students(self, view_name, view_args):
        url = reverse(view_name, args=([unicode(self.course.id)] + view_args))

        res_student = self.client.get(url)
        self.assertEquals(404, res_student.status_code, '{} should not be accessible for students'.format(view_name))

        self.client.logout()
        res_logged_out = self.client.get(url)
        self.assertRedirects(res_logged_out, '/login?next={}'.format(url),
                             msg_prefix='{} should redirect to login'.format(view_name))


class UniversityIDViewStaffTest(ModuleStoreTestCaseLoggedIn):
    """
    Integration tests for the instructor views of University ID.
    """

    ENROLL_USER = True
    LOGIN_STAFF = True

    def setUp(self):
        super(UniversityIDViewStaffTest, self).setUp()
        self.student_form_url = reverse('edraak_university:id', args=[unicode(self.course.id)])
        self.staff_list_url = reverse('edraak_university:id_list', args=[unicode(self.course.id)])

    def create_university_ids(self):
        """
        Creates initial data for tests that needs initial university IDs.
        """

        id_list = []

        for university_id in ['A5000C100', 'A5000C200', 'A5000C200', 'A5000C300']:
            obj = UniversityIDFactory.create(
                university_id=university_id,
                course_key=unicode(self.course.id),
            )
            obj.save()
            id_list.append(obj)

        return id_list

    def test_tab_link(self):
        self.assertNotEqual(self.student_form_url, self.staff_list_url)  # Sanity check for the test
        self.assertRedirects(self.client.get(self.student_form_url), self.staff_list_url,
                             msg_prefix='Should view the instructor ID list instead of the university ID page')

    def test_empty_list(self):
        res = self.client.get(self.staff_list_url)
        self.assertContains(res, 'No student have entered')
        self.assertNotContains(res, 'university-id-entry')

    def test_list_with_entries(self):
        university_ids = self.create_university_ids()

        res = self.client.get(self.staff_list_url)
        self.assertNotContains(res, 'No student have entered')
        self.assertContains(res, 'university-id-entry')
        self.assertEquals(res.content.count('university-id-entry'), len(university_ids),
                          msg='Should display all the IDs')

        self.assertEquals(res.content.count('conflicted'), 2,
                          msg='Should add the correct class for all duplicate IDs')

    def test_update_view(self):
        university_id = UniversityIDFactory.create()

        url = reverse('edraak_university:id_update', args=[unicode(self.course.id), university_id.pk])
        res = self.client.get(url)

        self.assertNotContains(res, 'john_cooper_1895', msg_prefix='Should not contain the username')
        self.assertContains(res, university_id.get_full_name(), msg_prefix='Should print the full name')
        self.assertContains(res, university_id.get_email(), msg_prefix='Should print the email')

    def test_update_conflicted_view(self):
        id_list = self.create_university_ids()

        res_list_conflicted = self.client.get(self.staff_list_url)
        self.assertEquals(res_list_conflicted.content.count('conflicted'), 2,
                          msg='Should add the correct class for all duplicate IDs')

        conflicted_id = id_list[1]
        update_url = reverse('edraak_university:id_update', args=[unicode(self.course.id), conflicted_id.pk])
        res_update = self.client.post(update_url, {
            'university_id': 'A5000C201',  # Correct the ID to avoid conflict
            'section_number': conflicted_id.section_number,
        })

        self.assertRedirects(res_update, self.staff_list_url, msg_prefix='Should redirect to the IDs list on success')

        res_list_good = self.client.get(self.staff_list_url)
        self.assertNotContains(res_list_good, 'conflicted', msg_prefix='Should not have any conflicted IDs')

    def test_delete_view(self):
        id_list = self.create_university_ids()
        id_to_delete = id_list[3]

        res_before_delete = self.client.get(self.staff_list_url)
        self.assertEquals(res_before_delete.content.count('university-id-entry'), 4,
                          msg='Should add the correct class for all duplicate IDs')

        self.assertContains(res_before_delete, id_to_delete.university_id,
                            msg_prefix='Should contain the ID before deleting it')

        delete_url = reverse('edraak_university:id_delete', args=[unicode(self.course.id), id_to_delete.pk])
        res_delete = self.client.post(delete_url)

        self.assertRedirects(res_delete, self.staff_list_url, msg_prefix='Should redirect to the IDs list on success')

        res_after_delete = self.client.get(self.staff_list_url)
        self.assertEquals(res_after_delete.content.count('university-id-entry'), 3, 'Should delete the ID')
        self.assertNotContains(res_after_delete, id_to_delete.university_id, msg_prefix='Should delete the correct ID')
