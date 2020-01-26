"""
Integration tests for the University ID by testing the views.
"""
from django.utils import timezone
from django.core.urlresolvers import reverse
from django.shortcuts import Http404
from django.conf import settings

from bs4 import BeautifulSoup
from mock import Mock, patch
import ddt

from opaque_keys.edx.locator import CourseLocator

from edraak_university.models import UniversityIDSettings
from edraak_university.views import UniversityIDView
from edxmako.shortcuts import marketing_link
from openedx.core.djangoapps.course_groups.cohorts import set_course_cohorted

from openedx.core.djangoapps.course_groups.tests.helpers import CohortFactory

from student.models import CourseEnrollment
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from edraak_university import helpers
from edraak_university.mixins import ContextMixin

from edraak_university.tests.factories import UniversityIDFactory
from edraak_tests.tests.helpers import ModuleStoreLoggedInTestCase


class ContextMixinTest(ModuleStoreTestCase):
    """
    Tests for ContextMixin context_data and helper methods.
    """

    def setUp(self):
        super(ContextMixinTest, self).setUp()

        course = CourseFactory.create()
        user = UserFactory.create()

        # Mocks Django generic view
        base_view_mock_class = type('BaseViewMock', (object,), {
            'get_context_data': lambda _: {},
        })

        # Mocks a University ID view
        view_mock_class = type('ViewMock', (ContextMixin, base_view_mock_class,), {
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
        self.assertEquals(data['course_key'], course_key)

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
class UniversityIDViewStudentTestCase(ModuleStoreLoggedInTestCase):
    """
    Integration tests for the University ID student views.
    """

    ENROLL_USER = True
    LOGIN_STAFF = False

    def setUp(self):
        super(UniversityIDViewStudentTestCase, self).setUp()
        set_course_cohorted(self.course.id, cohorted=True)
        self.cohort = CohortFactory.create(course_id=self.course.id)
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
            'cohort': self.cohort.id,
        }

        if data_overrides:
            form_data.update(data_overrides)

        return self.client.post(self.url, data=form_data)

    def test_student_success_view_message(self):
        url = reverse('edraak_university:id_success', args=[self.course.id])
        res = self.client.get(url)
        self.assertNotContains(res, 'View the Students List')
        self.assertContains(res, 'Your student university ID has been successfully')

    def test_disabled_university_id_redirect(self):
        disabled_course = CourseFactory.create(enable_university_id=False)
        CourseEnrollment.get_or_create_enrollment(self.user, disabled_course.id)
        set_course_cohorted(disabled_course.id, cohorted=True)

        student_form_url = reverse('edraak_university:id', args=[unicode(disabled_course.id)])
        course_root_url = reverse('course_root', args=[unicode(disabled_course.id)])

        res = self.client.get(student_form_url)
        self.assertRedirects(res, course_root_url, fetch_redirect_response=False)

    @patch('edraak_university.views.is_student_form_disabled', return_value=True)
    def test_disabled_form(self, _is_student_form_disabled):
        res = self.submit_form()
        self.assertContains(res, 'Registration is disabled. Contact your course instructor for help.')

    def test_basic_request(self):
        res = self.client.get(self.url)
        self.assertContains(res, 'university-id-form')
        self.assertContains(res, 'class="important"', msg_prefix='No information has been posted yet!')

        soup = BeautifulSoup(res.content, 'html.parser')
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

        soup = BeautifulSoup(res.content, 'html.parser')
        errors_list_elems = soup.select('ul.errorlist')
        self.assertTrue(len(errors_list_elems), 'Error list element should be shown')
        error_messages = unicode(errors_list_elems[0].text)
        self.assertIn('student university ID you have entered is too short', error_messages)

    @ddt.data('course_root', 'info')
    def test_sanity_check_for_legacy_course_pages(self, view_name):
        """
        Sanity check to ensure those pages are not open.
        """
        course_url = reverse(view_name, args=[unicode(self.course.id)])
        course_experience_url = reverse('openedx.course_experience.course_home', args=[unicode(self.course.id)])

        self.assertRedirects(self.client.get(course_url), course_experience_url,
                             fetch_redirect_response=False,
                             msg_prefix='{} should redirect to the new course experience home'.format(view_name))

    @ddt.data('about_course', 'courseware', 'openedx.course_experience.course_home')
    def test_view_course_pages_with_no_id(self, view_name):
        course_url = reverse(view_name, args=[unicode(self.course.id)])
        university_id_url = reverse('edraak_university:id', args=[unicode(self.course.id)])

        self.assertRedirects(self.client.get(course_url), university_id_url,
                             fetch_redirect_response=False,
                             msg_prefix='Should not allow access to {} before having a university ID'.format(view_name))

        res = self.submit_form()
        self.assertEquals(res.status_code, 302)  # Should successfully save the university ID

        self.assertContains(self.client.get(course_url), 'Skip to main',
                            msg_prefix='Should allow access to {} after entering valid university ID'.format(view_name))

    @ddt.unpack
    @ddt.data(
        {'view_name': 'edraak_university:id_staff', 'view_args': []},
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

    def get_initialized_view(self):
        kwargs = {'course_id': unicode(self.course.id)}
        view = UniversityIDView(**kwargs)
        view.request = Mock(user=self.user)
        view.kwargs = kwargs
        return view, kwargs

    def test_context_data_courses_url(self):
        view, kwargs = self.get_initialized_view()

        with patch.dict(settings.FEATURES, ENABLE_MKTG_SITE=False):
            data_disabled = view.get_context_data(**kwargs)
            url_disabled = reverse('about_course', args=[self.course.id])
            self.assertEquals(data_disabled['url_to_enroll'], url_disabled)

        with patch.dict(settings.FEATURES, ENABLE_MKTG_SITE=True):
            url_enabled = marketing_link('COURSES')
            data_enabled = view.get_context_data(**kwargs)
            self.assertEquals(data_enabled['url_to_enroll'], url_enabled)

    def test_initial_data(self):
        view, _kwargs = self.get_initialized_view()
        initial = view.get_initial()

        self.assertIn('full_name', initial)
        self.assertIn('cohort', initial)
        self.assertEquals(self.user.profile.name, initial['full_name'])

        self.submit_form()
        self.assertEquals(view.get_initial()['cohort'], self.cohort.id)

    def test_context_data_university_settings(self):
        view, kwargs = self.get_initialized_view()

        data_before = view.get_context_data(**kwargs)
        self.assertIsNone(data_before['terms_conditions'])
        self.assertIsNone(data_before['registration_end'])

        university_settings = UniversityIDSettings(
            course_key=self.course.id,
            registration_end_date=timezone.now().date(),
            terms_and_conditions='Hello World!',
        )
        university_settings.save()

        data_after = view.get_context_data(**kwargs)
        self.assertEquals(data_after['terms_conditions'], 'Hello World!')
        self.assertIn(unicode(timezone.now().date().year), unicode(data_after['registration_end']))

    def test_enroll_now_button(self):
        # Get course university page - user should be already enrolled
        response = self.client.get(self.url)

        # It must not contain (Enroll now)
        self.assertNotContains(response, 'Enroll now')

        # Un-enroll from course
        CourseEnrollment.unenroll(self.user, self.course.id, skip_refund=True)

        # Get course university page after un-enrollment
        response = self.client.get(self.url)

        # It must contain (Enroll now)
        self.assertContains(response, 'Enroll now')


@ddt.ddt
class UniversityIDStaffSettingsTestCase(ModuleStoreLoggedInTestCase):
    """
    Integration tests for the instructor view settings view of University ID.

    Hint: It's molded within the UniversityIDStaffView as a huge giant hack!
    """
    ENROLL_USER = True
    LOGIN_STAFF = True

    def setUp(self):
        super(UniversityIDStaffSettingsTestCase, self).setUp()
        self.form_url = reverse('edraak_university:id_staff', args=[self.course.id])
        self.success_url = reverse('edraak_university:id_settings_success', args=[self.course.id])

    def submit_form(self, form_data=None):
        """
        Submits the student university ID form and returns the response.
        """
        if not form_data:
            form_data = {}

        return self.client.post(self.form_url, data=form_data)

    @ddt.data(
        {},
        {'registration_end_date': '2010-10-25'},
        {'terms_and_conditions': 'Hello!'},
        {'terms_and_conditions': 'Hello!', 'registration_end_date': '2010-10-25'},
    )
    def test_submit_valid_form(self, overrides):
        res = self.submit_form(overrides)
        self.assertRedirects(res, self.success_url)

    def test_update_valid_form(self):
        kwargs = {'terms_and_conditions': 'Hello!', 'registration_end_date': '2010-10-25'}
        uni_settings = UniversityIDSettings(course_key=self.course.id, **kwargs)
        uni_settings.save()
        res = self.submit_form({'terms_and_conditions': 'Yikes!'})
        self.assertRedirects(res, self.success_url)

    def test_submit_invalid_form(self):
        res = self.submit_form({'registration_end_date': '10-25'})
        soup = BeautifulSoup(res.content, 'html.parser')
        errors_list_elems = soup.select('ul.errorlist')
        self.assertTrue(len(errors_list_elems), 'Error list element should be shown')


class UniversityIDViewStaffTestCase(ModuleStoreLoggedInTestCase):
    """
    Integration tests for the instructor views of University ID.
    """

    ENROLL_USER = True
    LOGIN_STAFF = True

    def setUp(self):
        super(UniversityIDViewStaffTestCase, self).setUp()
        set_course_cohorted(course_key=self.course.id, cohorted=True)
        self.student_form_url = reverse('edraak_university:id', args=[unicode(self.course.id)])
        self.staff_list_url = reverse('edraak_university:id_staff', args=[unicode(self.course.id)])

    def create_course(self):
        """
        Overrides `create_course` to enable university ID.
        """
        return CourseFactory.create(enable_university_id=True)

    def create_university_ids(self):
        """
        Creates initial data for tests that needs initial university IDs.
        """

        id_list = []

        for university_id in ['A5000C100', 'A5000C200', 'A5000C200', 'A5000C300']:
            obj = UniversityIDFactory.create(
                university_id=university_id,
                course_key=self.course.id,
            )
            obj.save()

            id_list.append(obj)

        return id_list

    def create_cohort(self, users):
        cohort = CohortFactory.create(
            course_id=self.course.id,
            users=users,
        )
        return cohort

    def test_tab_link(self):
        self.assertNotEqual(self.student_form_url, self.staff_list_url)  # Sanity check for the test
        self.assertRedirects(self.client.get(self.student_form_url), self.staff_list_url,
                             msg_prefix='Should view the instructor ID list instead of the university ID page')

    def test_empty_list(self):
        res = self.client.get(self.staff_list_url)
        self.assertContains(res, 'No student has entered')
        self.assertNotContains(res, 'university-id-entry')

    def test_staff_success_view_message(self):
        url = reverse('edraak_university:id_settings_success', args=[self.course.id])
        res = self.client.get(url)
        self.assertNotContains(res, 'Your student university ID has been successfully')
        self.assertContains(res, 'View the Students List')

    def test_list_with_entries(self):
        university_ids = self.create_university_ids()

        res = self.client.get(self.staff_list_url)
        self.assertNotContains(res, 'No student has entered')
        self.assertContains(res, 'university-id-entry')
        self.assertEquals(res.content.count('university-id-entry'), len(university_ids),
                          msg='Should display all the IDs')

        self.assertEquals(res.content.count('conflicted'), 2,
                          msg='Should add the correct class for all duplicate IDs')

    def test_update_view(self):
        id_list = self.create_university_ids()
        university_id = id_list[0]

        url = reverse('edraak_university:id_update', args=[self.course.id, university_id.pk])
        res = self.client.get(url)

        self.assertNotContains(res, 'john_cooper_1895', msg_prefix='Should not contain the username')
        self.assertContains(res, university_id.get_full_name(), msg_prefix='Should print the full name')
        self.assertContains(res, university_id.get_email(), msg_prefix='Should print the email')

    def test_update_conflicted_view(self):
        id_list = self.create_university_ids()
        self.create_cohort(users=[
            obj.user for obj in id_list
        ])

        res_list_conflicted = self.client.get(self.staff_list_url)
        self.assertEquals(res_list_conflicted.content.count('conflicted'), 2,
                          msg='Should add the correct class for all duplicate IDs')

        conflicted_id = id_list[1]
        update_url = reverse('edraak_university:id_update', args=[unicode(self.course.id), conflicted_id.pk])
        res_update = self.client.post(update_url, {
            'university_id': 'A5000C201',  # Correct the ID to avoid conflict
            'full_name': conflicted_id.get_full_name(),
            'email': conflicted_id.get_email(),
            'cohort': conflicted_id.get_cohort().id,
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
