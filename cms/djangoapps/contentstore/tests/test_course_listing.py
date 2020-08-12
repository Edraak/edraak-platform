"""
Unit tests for getting the list of courses for a user through iterating all courses and
by reversing group name formats.
"""
import random

import ddt
from ccx_keys.locator import CCXLocator
from django.conf import settings
from django.test import RequestFactory
from mock import Mock, patch
from opaque_keys.edx.locations import CourseLocator

from contentstore.tests.utils import AjaxEnabledTestClient
from contentstore.utils import delete_course
from contentstore.views.course import (
    AccessListFallback,
    _accessible_courses_iter_for_tests,
    _accessible_courses_list_from_groups,
    _accessible_courses_summary_iter,
    get_courses_accessible_to_user
)
from course_action_state.models import CourseRerunState
from student.roles import (
    CourseInstructorRole,
    CourseStaffRole,
    GlobalStaff,
    OrgInstructorRole,
    OrgStaffRole,
    UserBasedRole
)
from student.tests.factories import UserFactory
from xmodule.course_module import CourseSummary
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, check_mongo_calls

TOTAL_COURSES_COUNT = 10
USER_COURSES_COUNT = 1


@ddt.ddt
class TestCourseListing(ModuleStoreTestCase):
    """
    Unit tests for getting the list of courses for a logged in user
    """
    def setUp(self):
        """
        Add a user and a course
        """
        super(TestCourseListing, self).setUp()
        # create and log in a staff user.
        # create and log in a non-staff user
        self.user = UserFactory()
        self.factory = RequestFactory()
        self.request = self.factory.get('/course')
        self.request.user = self.user
        self.client = AjaxEnabledTestClient()
        self.client.login(username=self.user.username, password='test')

    def _create_course_with_access_groups(self, course_location, user=None, store=ModuleStoreEnum.Type.split):
        """
        Create dummy course with 'CourseFactory' and role (instructor/staff) groups
        """
        course = CourseFactory.create(
            org=course_location.org,
            number=course_location.course,
            run=course_location.run,
            default_store=store
        )
        self._add_role_access_to_user(user, course.id)
        return course

    def _add_role_access_to_user(self, user, course_id):
        """ Assign access roles to user in the course. """
        if user is not None:
            for role in [CourseInstructorRole, CourseStaffRole]:
                role(course_id).add_users(user)

    def tearDown(self):
        """
        Reverse the setup
        """
        self.client.logout()
        ModuleStoreTestCase.tearDown(self)

    def test_empty_course_listing(self):
        """
        Test on empty course listing, studio name is properly displayed
        """
        message = "Are you staff on an existing {studio_name} course?".format(studio_name=settings.STUDIO_SHORT_NAME)
        response = self.client.get('/home')
        self.assertEqual(response.status_code, 200)
        self.assertIn(message, response.content)

    def test_get_course_list(self):
        """
        Test getting courses with new access group format e.g. 'instructor_edx.course.run'
        """
        course_location = self.store.make_course_key('Org1', 'Course1', 'Run1')
        self._create_course_with_access_groups(course_location, self.user)

        # get courses through iterating all courses
        courses_iter, __ = _accessible_courses_iter_for_tests(self.request)
        courses_list = list(courses_iter)
        self.assertEqual(len(courses_list), 1)

        courses_summary_list, __ = _accessible_courses_summary_iter(self.request)
        self.assertEqual(len(list(courses_summary_list)), 1)

        # get courses by reversing group name formats
        courses_list_by_groups, __ = _accessible_courses_list_from_groups(self.request)
        self.assertEqual(len(courses_list_by_groups), 1)

        # check both course lists have same courses
        course_keys_in_course_list = [course.id for course in courses_list]
        course_keys_in_courses_list_by_groups = [course.id for course in courses_list_by_groups]

        self.assertEqual(course_keys_in_course_list, course_keys_in_courses_list_by_groups)

    def test_courses_list_with_ccx_courses(self):
        """
        Tests that CCX courses are filtered in course listing.
        """
        # Create a course and assign access roles to user.
        course_location = self.store.make_course_key('Org1', 'Course1', 'Run1')
        course = self._create_course_with_access_groups(course_location, self.user)

        # Create a ccx course key and add assign access roles to user.
        ccx_course_key = CCXLocator.from_course_locator(course.id, '1')
        self._add_role_access_to_user(self.user, ccx_course_key)

        # Test that CCX courses are filtered out.
        courses_list, __ = _accessible_courses_list_from_groups(self.request)
        self.assertEqual(len(courses_list), 1)
        self.assertNotIn(
            ccx_course_key,
            [course.id for course in courses_list]
        )

        # Get all courses which user has access.
        instructor_courses = UserBasedRole(self.user, CourseInstructorRole.ROLE).courses_with_role()
        staff_courses = UserBasedRole(self.user, CourseStaffRole.ROLE).courses_with_role()
        all_courses = (instructor_courses | staff_courses)

        # Verify that CCX course exists in access but filtered by `_accessible_courses_list_from_groups`.
        self.assertIn(
            ccx_course_key,
            [access.course_id for access in all_courses]
        )

        # Verify that CCX courses are filtered out while iterating over all courses
        mocked_ccx_course = Mock(id=ccx_course_key)
        with patch('xmodule.modulestore.mixed.MixedModuleStore.get_course_summaries', return_value=[mocked_ccx_course]):
            courses_iter, __ = _accessible_courses_iter_for_tests(self.request)
            self.assertEqual(len(list(courses_iter)), 0)

    @ddt.data(
        (ModuleStoreEnum.Type.split, 3),
        (ModuleStoreEnum.Type.mongo, 2)
    )
    @ddt.unpack
    def test_staff_course_listing(self, default_store, mongo_calls):
        """
        Create courses and verify they take certain amount of mongo calls to call get_courses_accessible_to_user.
        Also verify that fetch accessible courses list for staff user returns CourseSummary instances.
        """

        # Assign & verify staff role to the user
        GlobalStaff().add_users(self.user)
        self.assertTrue(GlobalStaff().has_user(self.user))

        with self.store.default_store(default_store):
            # Create few courses
            for num in xrange(TOTAL_COURSES_COUNT):
                course_location = self.store.make_course_key('Org', 'CreatedCourse' + str(num), 'Run')
                self._create_course_with_access_groups(course_location, self.user, default_store)

        # Fetch accessible courses list & verify their count
        courses_list_by_staff, __ = get_courses_accessible_to_user(self.request)
        self.assertEqual(len(list(courses_list_by_staff)), TOTAL_COURSES_COUNT)

        # Verify fetched accessible courses list is a list of CourseSummery instances
        self.assertTrue(all(isinstance(course, CourseSummary) for course in courses_list_by_staff))

        # Now count the db queries for staff
        with check_mongo_calls(mongo_calls):
            list(_accessible_courses_summary_iter(self.request))

    @ddt.data(ModuleStoreEnum.Type.split, ModuleStoreEnum.Type.mongo)
    def test_get_course_list_with_invalid_course_location(self, store):
        """
        Test getting courses with invalid course location (course deleted from modulestore).
        """
        with self.store.default_store(store):
            course_key = self.store.make_course_key('Org', 'Course', 'Run')
            self._create_course_with_access_groups(course_key, self.user, store)

        # get courses through iterating all courses
        courses_iter, __ = _accessible_courses_iter_for_tests(self.request)
        courses_list = list(courses_iter)
        self.assertEqual(len(courses_list), 1)

        courses_summary_iter, __ = _accessible_courses_summary_iter(self.request)
        courses_summary_list = list(courses_summary_iter)

        # Verify fetched accessible courses list is a list of CourseSummery instances and only one course
        # is returned
        self.assertTrue(all(isinstance(course, CourseSummary) for course in courses_summary_list))
        self.assertEqual(len(courses_summary_list), 1)

        # get courses by reversing group name formats
        courses_list_by_groups, __ = _accessible_courses_list_from_groups(self.request)
        self.assertEqual(len(courses_list_by_groups), 1)

        course_keys_in_course_list = [course.id for course in courses_list]
        course_keys_in_courses_list_by_groups = [course.id for course in courses_list_by_groups]
        # check course lists have same courses
        self.assertEqual(course_keys_in_course_list, course_keys_in_courses_list_by_groups)
        # now delete this course and re-add user to instructor group of this course
        delete_course(course_key, self.user.id)

        CourseInstructorRole(course_key).add_users(self.user)

        # Get courses through iterating all courses
        courses_iter, __ = _accessible_courses_iter_for_tests(self.request)

        # Get course summaries by iterating all courses
        courses_summary_iter, __ = _accessible_courses_summary_iter(self.request)

        # Get courses by reversing group name formats
        courses_list_by_groups, __ = _accessible_courses_list_from_groups(self.request)

        # Test that course list returns no course
        self.assertEqual(
            [len(list(courses_iter)), len(courses_list_by_groups), len(list(courses_summary_iter))],
            [0, 0, 0]
        )

    @ddt.data(
        (ModuleStoreEnum.Type.split, 3, 3),
        (ModuleStoreEnum.Type.mongo, 2, 2)
    )
    @ddt.unpack
    def test_course_listing_performance(self, store, courses_list_from_group_calls, courses_list_calls):
        """
        Create large number of courses and give access of some of these courses to the user and
        compare the time to fetch accessible courses for the user through traversing all courses and
        reversing django groups
        """
        # create list of random course numbers which will be accessible to the user
        user_course_ids = random.sample(range(TOTAL_COURSES_COUNT), USER_COURSES_COUNT)

        # create courses and assign those to the user which have their number in user_course_ids
        with self.store.default_store(store):
            for number in range(TOTAL_COURSES_COUNT):
                org = 'Org{0}'.format(number)
                course = 'Course{0}'.format(number)
                run = 'Run{0}'.format(number)
                course_location = self.store.make_course_key(org, course, run)
                if number in user_course_ids:
                    self._create_course_with_access_groups(course_location, self.user, store=store)
                else:
                    self._create_course_with_access_groups(course_location, store=store)

        # get courses by iterating through all courses
        courses_iter, __ = _accessible_courses_iter_for_tests(self.request)
        self.assertEqual(len(list(courses_iter)), USER_COURSES_COUNT)

        # again get courses by iterating through all courses
        courses_iter, __ = _accessible_courses_iter_for_tests(self.request)
        self.assertEqual(len(list(courses_iter)), USER_COURSES_COUNT)

        # get courses by reversing django groups
        courses_list, __ = _accessible_courses_list_from_groups(self.request)
        self.assertEqual(len(courses_list), USER_COURSES_COUNT)

        # again get courses by reversing django groups
        courses_list, __ = _accessible_courses_list_from_groups(self.request)
        self.assertEqual(len(courses_list), USER_COURSES_COUNT)

        # Now count the db queries
        with check_mongo_calls(courses_list_from_group_calls):
            _accessible_courses_list_from_groups(self.request)

        with check_mongo_calls(courses_list_calls):
            list(_accessible_courses_iter_for_tests(self.request))
        # Calls:
        #    1) query old mongo
        #    2) get_more on old mongo
        #    3) query split (but no courses so no fetching of data)

    @ddt.data(ModuleStoreEnum.Type.split, ModuleStoreEnum.Type.mongo)
    def test_course_listing_errored_deleted_courses(self, store):
        """
        Create good courses, courses that won't load, and deleted courses which still have
        roles. Test course listing.
        """
        with self.store.default_store(store):
            course_location = self.store.make_course_key('testOrg', 'testCourse', 'RunBabyRun')
            self._create_course_with_access_groups(course_location, self.user, store)

            course_location = self.store.make_course_key('testOrg', 'doomedCourse', 'RunBabyRun')
            self._create_course_with_access_groups(course_location, self.user, store)
            self.store.delete_course(course_location, self.user.id)

        courses_list, __ = _accessible_courses_list_from_groups(self.request)
        self.assertEqual(len(courses_list), 1, courses_list)

    @ddt.data(OrgStaffRole('AwesomeOrg'), OrgInstructorRole('AwesomeOrg'))
    def test_course_listing_org_permissions(self, role):
        """
        Create multiple courses within the same org.  Verify that someone with org-wide permissions can access
        all of them.
        """
        org_course_one = self.store.make_course_key('AwesomeOrg', 'Course1', 'RunBabyRun')
        CourseFactory.create(
            org=org_course_one.org,
            number=org_course_one.course,
            run=org_course_one.run
        )

        org_course_two = self.store.make_course_key('AwesomeOrg', 'Course2', 'RunBabyRun')
        CourseFactory.create(
            org=org_course_two.org,
            number=org_course_two.course,
            run=org_course_two.run
        )

        # Two types of org-wide roles have edit permissions: staff and instructor.  We test both
        role.add_users(self.user)

        with self.assertRaises(AccessListFallback):
            _accessible_courses_list_from_groups(self.request)
        courses_list, __ = get_courses_accessible_to_user(self.request)

        # Verify fetched accessible courses list is a list of CourseSummery instances and test expacted
        # course count is returned
        self.assertEqual(len(list(courses_list)), 2)
        self.assertTrue(all(isinstance(course, CourseSummary) for course in courses_list))

    def test_course_listing_with_actions_in_progress(self):
        sourse_course_key = CourseLocator('source-Org', 'source-Course', 'source-Run')

        num_courses_to_create = 3
        courses = [
            self._create_course_with_access_groups(
                CourseLocator('Org', 'CreatedCourse' + str(num), 'Run'),
                self.user,
            )
            for num in range(num_courses_to_create)
        ]
        courses_in_progress = [
            self._create_course_with_access_groups(
                CourseLocator('Org', 'InProgressCourse' + str(num), 'Run'),
                self.user,
            )
            for num in range(num_courses_to_create)
        ]

        # simulate initiation of course actions
        for course in courses_in_progress:
            CourseRerunState.objects.initiated(
                sourse_course_key, destination_course_key=course.id, user=self.user, display_name="test course"
            )

        # verify return values
        def _set_of_course_keys(course_list, key_attribute_name='id'):
            """Returns a python set of course keys by accessing the key with the given attribute name."""
            return set(getattr(c, key_attribute_name) for c in course_list)

        found_courses, unsucceeded_course_actions = _accessible_courses_iter_for_tests(self.request)
        self.assertSetEqual(_set_of_course_keys(courses + courses_in_progress), _set_of_course_keys(found_courses))
        self.assertSetEqual(
            _set_of_course_keys(courses_in_progress), _set_of_course_keys(unsucceeded_course_actions, 'course_key')
        )
