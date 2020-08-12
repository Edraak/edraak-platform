"""
Helpers for courseware tests.
"""
from datetime import timedelta
import json

from django.contrib import messages
from django.contrib.auth.models import User
from django.test import TestCase
from django.test.client import Client, RequestFactory
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import get_language
from six import text_type

from courseware.access import has_access
from courseware.masquerade import handle_ajax, setup_masquerade
from edxmako.shortcuts import render_to_string
from lms.djangoapps.courseware.date_summary import verified_upgrade_deadline_link
from lms.djangoapps.lms_xblock.field_data import LmsFieldData
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.lib.url_utils import quote_slashes
from student.models import Registration, CourseEnrollment
from student.tests.factories import CourseEnrollmentFactory, UserFactory
from util.date_utils import strftime_localized
from xblock.field_data import DictFieldData
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.django_utils import TEST_DATA_MONGO_MODULESTORE, ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.tests import get_test_descriptor_system, get_test_system


class BaseTestXmodule(ModuleStoreTestCase):
    """Base class for testing Xmodules with mongo store.

    This class prepares course and users for tests:
        1. create test course;
        2. create, enroll and login users for this course;

    Any xmodule should overwrite only next parameters for test:
        1. CATEGORY
        2. DATA or METADATA
        3. MODEL_DATA
        4. COURSE_DATA and USER_COUNT if needed

    This class should not contain any tests, because CATEGORY
    should be defined in child class.
    """
    MODULESTORE = TEST_DATA_MONGO_MODULESTORE

    USER_COUNT = 2
    COURSE_DATA = {}

    # Data from YAML common/lib/xmodule/xmodule/templates/NAME/default.yaml
    CATEGORY = "vertical"
    DATA = ''
    # METADATA must be overwritten for every instance that uses it. Otherwise,
    # if we'll change it in the tests, it will be changed for all other instances
    # of parent class.
    METADATA = {}
    MODEL_DATA = {'data': '<some_module></some_module>'}

    def new_module_runtime(self):
        """
        Generate a new ModuleSystem that is minimally set up for testing
        """
        return get_test_system(course_id=self.course.id)

    def new_descriptor_runtime(self):
        runtime = get_test_descriptor_system()
        runtime.get_block = modulestore().get_item
        return runtime

    def initialize_module(self, **kwargs):
        kwargs.update({
            'parent_location': self.section.location,
            'category': self.CATEGORY
        })

        self.item_descriptor = ItemFactory.create(**kwargs)

        self.runtime = self.new_descriptor_runtime()

        field_data = {}
        field_data.update(self.MODEL_DATA)
        student_data = DictFieldData(field_data)
        self.item_descriptor._field_data = LmsFieldData(self.item_descriptor._field_data, student_data)

        self.item_descriptor.xmodule_runtime = self.new_module_runtime()

        self.item_url = unicode(self.item_descriptor.location)

    def setup_course(self):
        self.course = CourseFactory.create(data=self.COURSE_DATA)

        # Turn off cache.
        modulestore().request_cache = None
        modulestore().metadata_inheritance_cache_subsystem = None

        chapter = ItemFactory.create(
            parent_location=self.course.location,
            category="sequential",
        )
        self.section = ItemFactory.create(
            parent_location=chapter.location,
            category="sequential"
        )

        # username = robot{0}, password = 'test'
        self.users = [
            UserFactory.create()
            for dummy0 in range(self.USER_COUNT)
        ]

        for user in self.users:
            CourseEnrollmentFactory.create(user=user, course_id=self.course.id)

        # login all users for acces to Xmodule
        self.clients = {user.username: Client() for user in self.users}
        self.login_statuses = [
            self.clients[user.username].login(
                username=user.username, password='test')
            for user in self.users
        ]

        self.assertTrue(all(self.login_statuses))

    def setUp(self):
        super(BaseTestXmodule, self).setUp()
        self.setup_course()
        self.initialize_module(metadata=self.METADATA, data=self.DATA)

    def get_url(self, dispatch):
        """Return item url with dispatch."""
        return reverse(
            'xblock_handler',
            args=(unicode(self.course.id), quote_slashes(self.item_url), 'xmodule_handler', dispatch)
        )


class XModuleRenderingTestBase(BaseTestXmodule):

    def new_module_runtime(self):
        """
        Create a runtime that actually does html rendering
        """
        runtime = super(XModuleRenderingTestBase, self).new_module_runtime()
        runtime.render_template = render_to_string
        return runtime


class LoginEnrollmentTestCase(TestCase):
    """
    Provides support for user creation,
    activation, login, and course enrollment.
    """
    user = None

    def setup_user(self):
        """
        Create a user account, activate, and log in.
        """
        self.email = 'foo@test.com'
        self.password = 'bar'
        self.username = 'test'
        self.user = self.create_account(
            self.username,
            self.email,
            self.password,
        )
        # activate_user re-fetches and returns the activated user record
        self.user = self.activate_user(self.email)
        self.login(self.email, self.password)

    def assert_request_status_code(self, status_code, url, method="GET", **kwargs):
        make_request = getattr(self.client, method.lower())
        response = make_request(url, **kwargs)
        self.assertEqual(
            response.status_code, status_code,
            "{method} request to {url} returned status code {actual}, "
            "expected status code {expected}".format(
                method=method, url=url,
                actual=response.status_code, expected=status_code
            )
        )
        return response

    def assert_account_activated(self, url, method="GET", **kwargs):
        make_request = getattr(self.client, method.lower())
        response = make_request(url, **kwargs)
        message_list = list(messages.get_messages(response.wsgi_request))
        self.assertEqual(len(message_list), 1)
        self.assertIn("success", message_list[0].tags)
        self.assertTrue("You have activated your account." in message_list[0].message)

    # ============ User creation and login ==============

    def login(self, email, password):
        """
        Login, check that the corresponding view's response has a 200 status code.
        """
        resp = self.client.post(reverse('user_api_login_session'),
                                {'email': email, 'password': password})
        self.assertEqual(resp.status_code, 200)

    def logout(self):
        """
        Logout; check that the HTTP response code indicates redirection
        as expected.
        """
        self.assert_request_status_code(200, reverse('logout'))

    def create_account(self, username, email, password):
        """
        Create the account and check that it worked.
        """
        url = reverse('user_api_registration')
        request_data = {
            'username': username,
            'email': email,
            'password': password,
            'name': 'username',
            'terms_of_service': 'true',
            'honor_code': 'true',
        }
        resp = self.assert_request_status_code(200, url, method="POST", data=request_data)
        # Check both that the user is created, and inactive
        user = User.objects.get(email=email)
        self.assertFalse(user.is_active)
        return user

    def activate_user(self, email):
        """
        Look up the activation key for the user, then hit the activate view.
        No error checking.
        """
        activation_key = Registration.objects.get(user__email=email).activation_key
        # and now we try to activate
        url = reverse('activate', kwargs={'key': activation_key})
        self.assert_account_activated(url)
        # Now make sure that the user is now actually activated
        user = User.objects.get(email=email)
        self.assertTrue(user.is_active)
        # And return the user we fetched.
        return user

    def enroll(self, course, verify=False):
        """
        Try to enroll and return boolean indicating result.
        `course` is an instance of CourseDescriptor.
        `verify` is an optional boolean parameter specifying whether we
        want to verify that the student was successfully enrolled
        in the course.
        """
        resp = self.client.post(reverse('change_enrollment'), {
            'enrollment_action': 'enroll',
            'course_id': text_type(course.id),
            'check_access': True,
        })
        result = resp.status_code == 200
        if verify:
            self.assertTrue(result)
        return result

    def unenroll(self, course):
        """
        Unenroll the currently logged-in user, and check that it worked.
        `course` is an instance of CourseDescriptor.
        """
        url = reverse('change_enrollment')
        request_data = {
            'enrollment_action': 'unenroll',
            'course_id': text_type(course.id),
        }
        self.assert_request_status_code(200, url, method="POST", data=request_data)


class CourseAccessTestMixin(TestCase):
    """
    Utility mixin for asserting access (or lack thereof) to courses.
    If relevant, also checks access for courses' corresponding CourseOverviews.
    """

    def assertCanAccessCourse(self, user, action, course):
        """
        Assert that a user has access to the given action for a given course.

        Test with both the given course and with a CourseOverview of the given
        course.

        Arguments:
            user (User): a user.
            action (str): type of access to test.
            course (CourseDescriptor): a course.
        """
        self.assertTrue(has_access(user, action, course))
        self.assertTrue(has_access(user, action, CourseOverview.get_from_id(course.id)))

    def assertCannotAccessCourse(self, user, action, course):
        """
        Assert that a user lacks access to the given action the given course.

        Test with both the given course and with a CourseOverview of the given
        course.

        Arguments:
            user (User): a user.
            action (str): type of access to test.
            course (CourseDescriptor): a course.

        Note:
            It may seem redundant to have one method for testing access
            and another method for testing lack thereof (why not just combine
            them into one method with a boolean flag?), but it makes reading
            stack traces of failed tests easier to understand at a glance.
        """
        self.assertFalse(has_access(user, action, course))
        self.assertFalse(has_access(user, action, CourseOverview.get_from_id(course.id)))


def masquerade_as_group_member(user, course, partition_id, group_id):
    """
    Installs a masquerade for the specified user and course, to enable
    the user to masquerade as belonging to the specific partition/group
    combination.

    Arguments:
        user (User): a user.
        course (CourseDescriptor): a course.
        partition_id (int): the integer partition id, referring to partitions already
           configured in the course.
        group_id (int); the integer group id, within the specified partition.

    Returns: the status code for the AJAX response to update the user's masquerade for
        the specified course.
    """
    request = _create_mock_json_request(
        user,
        data={"role": "student", "user_partition_id": partition_id, "group_id": group_id}
    )
    response = handle_ajax(request, unicode(course.id))
    setup_masquerade(request, course.id, True)
    return response.status_code


def _create_mock_json_request(user, data, method='POST'):
    """
    Returns a mock JSON request for the specified user.
    """
    factory = RequestFactory()
    request = factory.generic(method, '/', content_type='application/json', data=json.dumps(data))
    request.user = user
    request.session = {}
    return request


def get_expiration_banner_text(user, course, language='en-us'):
    """
    Get text for banner that messages user course expiration date
    for different tests that depend on it.
    """
    expiration_date = now() + timedelta(weeks=4)
    upgrade_link = verified_upgrade_deadline_link(user=user, course=course)
    enrollment = CourseEnrollment.get_enrollment(user, course.id)
    upgrade_deadline = enrollment.upgrade_deadline
    if upgrade_deadline is None or now() < upgrade_deadline:
        upgrade_deadline = enrollment.course_upgrade_deadline

    language_is_es = language and language.split('-')[0].lower() == 'es'
    if language_is_es:
        formatted_expiration_date = strftime_localized(expiration_date, '%-d de %b. de %Y').lower()
    else:
        formatted_expiration_date = strftime_localized(expiration_date, '%b. %-d, %Y')

    if upgrade_deadline:
        if language_is_es:
            formatted_upgrade_deadline = strftime_localized(upgrade_deadline, '%-d de %b. de %Y').lower()
        else:
            formatted_upgrade_deadline = strftime_localized(upgrade_deadline, '%b. %-d, %Y')

        bannerText = '<strong>Audit Access Expires {expiration_date}</strong><br>\
                     You lose all access to this course, including your progress, on {expiration_date}.\
                     <br>Upgrade by {upgrade_deadline} to get unlimited access to the course as long as it exists\
                     on the site. <a href="{upgrade_link}">Upgrade now<span class="sr-only"> to retain access past\
                     {expiration_date}</span></a>'.format(
            expiration_date=formatted_expiration_date,
            upgrade_link=upgrade_link,
            upgrade_deadline=formatted_upgrade_deadline
        )
    else:
        bannerText = '<strong>Audit Access Expires {expiration_date}</strong><br>\
                     You lose all access to this course, including your progress, on {expiration_date}.\
                     '.format(
            expiration_date=formatted_expiration_date
        )
    return bannerText
