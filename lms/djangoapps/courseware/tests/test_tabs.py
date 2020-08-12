"""
Test cases for tabs.
"""
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from django.http import Http404
from milestones.tests.utils import MilestonesTestCaseMixin
from mock import MagicMock, Mock, patch
from six import text_type
from crum import set_current_request

from courseware.courses import get_course_by_id
from courseware.tabs import (
    CourseInfoTab,
    CoursewareTab,
    ExternalDiscussionCourseTab,
    ExternalLinkCourseTab,
    ProgressTab,
    get_course_tab_list
)
from courseware.tests.factories import InstructorFactory, StaffFactory
from courseware.tests.helpers import LoginEnrollmentTestCase
from courseware.views.views import StaticCourseTabView, get_static_tab_fragment
from openedx.core.djangoapps.waffle_utils.testutils import override_waffle_flag
from openedx.core.djangolib.testing.utils import get_mock_request
from openedx.core.lib.tests import attr
from openedx.features.course_experience import UNIFIED_COURSE_TAB_FLAG
from student.models import CourseEnrollment
from student.tests.factories import UserFactory
from util.milestones_helpers import (
    add_course_content_milestone,
    add_course_milestone,
    add_milestone,
    get_milestone_relationship_types
)
from xmodule import tabs as xmodule_tabs
from xmodule.modulestore.tests.django_utils import (
    TEST_DATA_MIXED_MODULESTORE,
    ModuleStoreTestCase,
    SharedModuleStoreTestCase
)
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore.tests.utils import TEST_DATA_DIR
from xmodule.modulestore.xml_importer import import_course_from_xml


class TabTestCase(SharedModuleStoreTestCase):
    """Base class for Tab-related test cases."""
    @classmethod
    def setUpClass(cls):
        super(TabTestCase, cls).setUpClass()

        cls.course = CourseFactory.create(org='edX', course='toy', run='2012_Fall')
        cls.fake_dict_tab = {'fake_key': 'fake_value'}
        cls.books = None

    def setUp(self):
        super(TabTestCase, self).setUp()
        self.reverse = lambda name, args: "name/{0}/args/{1}".format(name, ",".join(str(a) for a in args))

    def create_mock_user(self, is_staff=True, is_enrolled=True):
        """
        Creates a mock user with the specified properties.
        """
        user = UserFactory(is_staff=is_staff)
        user.is_enrolled = is_enrolled
        return user

    def is_tab_enabled(self, tab, course, user):
        """
        Returns true if the specified tab is enabled.
        """
        return tab.is_enabled(course, user=user)

    def set_up_books(self, num_books):
        """Initializes the textbooks in the course and adds the given number of books to each textbook"""
        self.books = [MagicMock() for _ in range(num_books)]
        for book_index, book in enumerate(self.books):
            book.title = 'Book{0}'.format(book_index)
        self.course.textbooks = self.books
        self.course.pdf_textbooks = self.books
        self.course.html_textbooks = self.books

    def check_tab(
            self,
            tab_class,
            dict_tab,
            expected_link,
            expected_tab_id,
            expected_name='same',
            invalid_dict_tab=None,
    ):
        """
        Helper method to verify a tab class.

        'tab_class' is the class of the tab that is being tested
        'dict_tab' is the raw dictionary value of the tab
        'expected_link' is the expected value for the hyperlink of the tab
        'expected_tab_id' is the expected value for the unique id of the tab
        'expected_name' is the expected value for the name of the tab
        'invalid_dict_tab' is an invalid dictionary value for the tab.
            Can be 'None' if the given tab class does not have any keys to validate.
        """
        # create tab
        tab = tab_class(tab_dict=dict_tab)

        # name is as expected
        self.assertEqual(tab.name, expected_name)

        # link is as expected
        self.assertEqual(tab.link_func(self.course, self.reverse), expected_link)

        # verify active page name
        self.assertEqual(tab.tab_id, expected_tab_id)

        # validate tab
        self.assertTrue(tab.validate(dict_tab))
        if invalid_dict_tab:
            with self.assertRaises(xmodule_tabs.InvalidTabsException):
                tab.validate(invalid_dict_tab)

        # check get and set methods
        self.check_get_and_set_methods(tab)

        # check to_json and from_json methods
        self.check_tab_json_methods(tab)

        # check equality methods
        self.check_tab_equality(tab, dict_tab)

        # return tab for any additional tests
        return tab

    def check_tab_equality(self, tab, dict_tab):
        """Tests the equality methods on the given tab"""
        self.assertEquals(tab, dict_tab)  # test __eq__
        ne_dict_tab = dict_tab
        ne_dict_tab['type'] = 'fake_type'
        self.assertNotEquals(tab, ne_dict_tab)  # test __ne__: incorrect type
        self.assertNotEquals(tab, {'fake_key': 'fake_value'})  # test __ne__: missing type

    def check_tab_json_methods(self, tab):
        """Tests the json from and to methods on the given tab"""
        serialized_tab = tab.to_json()
        deserialized_tab = tab.from_json(serialized_tab)
        self.assertEquals(serialized_tab, deserialized_tab)

    def check_can_display_results(
            self,
            tab,
            expected_value=True,
            for_authenticated_users_only=False,
            for_staff_only=False,
            for_enrolled_users_only=False
    ):
        """Checks can display results for various users"""
        if for_staff_only:
            user = self.create_mock_user(is_staff=True, is_enrolled=True)
            self.assertEquals(expected_value, self.is_tab_enabled(tab, self.course, user))
        if for_authenticated_users_only:
            user = self.create_mock_user(is_staff=False, is_enrolled=False)
            self.assertEquals(expected_value, self.is_tab_enabled(tab, self.course, user))
            assert False
        if not for_staff_only and not for_authenticated_users_only and not for_enrolled_users_only:
            user = AnonymousUser()
            self.assertEquals(expected_value, self.is_tab_enabled(tab, self.course, user))
        if for_enrolled_users_only:
            user = self.create_mock_user(is_staff=False, is_enrolled=True)
            self.assertEquals(expected_value, self.is_tab_enabled(tab, self.course, user))

    def check_get_and_set_methods(self, tab):
        """Test __getitem__ and __setitem__ calls"""
        self.assertEquals(tab['type'], tab.type)
        self.assertEquals(tab['tab_id'], tab.tab_id)
        with self.assertRaises(KeyError):
            _ = tab['invalid_key']

        self.check_get_and_set_method_for_key(tab, 'name')
        self.check_get_and_set_method_for_key(tab, 'tab_id')
        with self.assertRaises(KeyError):
            tab['invalid_key'] = 'New Value'

    def check_get_and_set_method_for_key(self, tab, key):
        """Test __getitem__ and __setitem__ for the given key"""
        old_value = tab[key]
        new_value = 'New Value'
        tab[key] = new_value
        self.assertEquals(tab[key], new_value)
        tab[key] = old_value
        self.assertEquals(tab[key], old_value)


class TextbooksTestCase(TabTestCase):
    """Test cases for Textbook Tab."""

    def setUp(self):
        super(TextbooksTestCase, self).setUp()

        self.set_up_books(2)

        self.dict_tab = MagicMock()
        self.course.tabs = [
            xmodule_tabs.CourseTab.load('textbooks'),
            xmodule_tabs.CourseTab.load('pdf_textbooks'),
            xmodule_tabs.CourseTab.load('html_textbooks'),
        ]
        self.num_textbook_tabs = sum(1 for tab in self.course.tabs if tab.type in [
            'textbooks', 'pdf_textbooks', 'html_textbooks'
        ])
        self.num_textbooks = self.num_textbook_tabs * len(self.books)

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_TEXTBOOK": True})
    def test_textbooks_enabled(self):

        type_to_reverse_name = {'textbook': 'book', 'pdftextbook': 'pdf_book', 'htmltextbook': 'html_book'}

        num_textbooks_found = 0
        user = self.create_mock_user(is_staff=False, is_enrolled=True)
        for tab in xmodule_tabs.CourseTabList.iterate_displayable(self.course, user=user):
            # verify all textbook type tabs
            if tab.type == 'single_textbook':
                book_type, book_index = tab.tab_id.split("/", 1)
                expected_link = self.reverse(
                    type_to_reverse_name[book_type],
                    args=[text_type(self.course.id), book_index]
                )
                self.assertEqual(tab.link_func(self.course, self.reverse), expected_link)
                self.assertTrue(tab.name.startswith('Book{0}'.format(book_index)))
                num_textbooks_found = num_textbooks_found + 1
        self.assertEquals(num_textbooks_found, self.num_textbooks)


@attr(shard=1)
class StaticTabDateTestCase(LoginEnrollmentTestCase, SharedModuleStoreTestCase):
    """Test cases for Static Tab Dates."""

    MODULESTORE = TEST_DATA_MIXED_MODULESTORE

    @classmethod
    def setUpClass(cls):
        super(StaticTabDateTestCase, cls).setUpClass()
        cls.course = CourseFactory.create()
        cls.page = ItemFactory.create(
            category="static_tab", parent_location=cls.course.location,
            data="OOGIE BLOOGIE", display_name="new_tab"
        )
        cls.course.tabs.append(xmodule_tabs.CourseTab.load('static_tab', name='New Tab', url_slug='new_tab'))
        cls.course.save()

    def test_logged_in(self):
        self.setup_user()
        url = reverse('static_tab', args=[text_type(self.course.id), 'new_tab'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)

    def test_anonymous_user(self):
        url = reverse('static_tab', args=[text_type(self.course.id), 'new_tab'])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)

    def test_invalid_course_key(self):
        self.setup_user()
        self.addCleanup(set_current_request, None)
        request = get_mock_request(self.user)
        with self.assertRaises(Http404):
            StaticCourseTabView().get(request, course_id='edX/toy', tab_slug='new_tab')

    def test_get_static_tab_fragment(self):
        self.setup_user()
        course = get_course_by_id(self.course.id)
        self.addCleanup(set_current_request, None)
        request = get_mock_request(self.user)
        tab = xmodule_tabs.CourseTabList.get_tab_by_slug(course.tabs, 'new_tab')

        # Test render works okay
        tab_content = get_static_tab_fragment(request, course, tab).content
        self.assertIn(text_type(self.course.id), tab_content)
        self.assertIn('static_tab', tab_content)

        # Test when render raises an exception
        with patch('courseware.views.views.get_module') as mock_module_render:
            mock_module_render.return_value = MagicMock(
                render=Mock(side_effect=Exception('Render failed!'))
            )
            static_tab_content = get_static_tab_fragment(request, course, tab).content
            self.assertIn("this module is temporarily unavailable", static_tab_content)


@attr(shard=1)
class StaticTabDateTestCaseXML(LoginEnrollmentTestCase, ModuleStoreTestCase):
    """
    Tests for the static tab dates of an XML course
    """

    MODULESTORE = TEST_DATA_MIXED_MODULESTORE

    def setUp(self):
        """
        Set up the tests
        """
        super(StaticTabDateTestCaseXML, self).setUp()

        # The following XML test course (which lives at common/test/data/2014)
        # is closed; we're testing that tabs still appear when
        # the course is already closed
        self.xml_course_key = self.store.make_course_key('edX', 'detached_pages', '2014')
        import_course_from_xml(
            self.store,
            'test_user',
            TEST_DATA_DIR,
            source_dirs=['2014'],
            static_content_store=None,
            target_id=self.xml_course_key,
            raise_on_failure=True,
            create_if_not_present=True,
        )

        # this text appears in the test course's tab
        # common/test/data/2014/tabs/8e4cce2b4aaf4ba28b1220804619e41f.html
        self.xml_data = "static 463139"
        self.xml_url = "8e4cce2b4aaf4ba28b1220804619e41f"

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_logged_in_xml(self):
        self.setup_user()
        url = reverse('static_tab', args=[text_type(self.xml_course_key), self.xml_url])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.xml_data, resp.content)

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_anonymous_user_xml(self):
        url = reverse('static_tab', args=[text_type(self.xml_course_key), self.xml_url])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.xml_data, resp.content)


@attr(shard=1)
@patch.dict('django.conf.settings.FEATURES', {'ENTRANCE_EXAMS': True})
class EntranceExamsTabsTestCase(LoginEnrollmentTestCase, ModuleStoreTestCase, MilestonesTestCaseMixin):
    """
    Validate tab behavior when dealing with Entrance Exams
    """
    MODULESTORE = TEST_DATA_MIXED_MODULESTORE

    @patch.dict('django.conf.settings.FEATURES', {'ENTRANCE_EXAMS': True})
    def setUp(self):
        """
        Test case scaffolding
        """
        super(EntranceExamsTabsTestCase, self).setUp()

        self.course = CourseFactory.create()
        self.instructor_tab = ItemFactory.create(
            category="instructor", parent_location=self.course.location,
            data="Instructor Tab", display_name="Instructor"
        )
        self.extra_tab_2 = ItemFactory.create(
            category="static_tab", parent_location=self.course.location,
            data="Extra Tab", display_name="Extra Tab 2"
        )
        self.extra_tab_3 = ItemFactory.create(
            category="static_tab", parent_location=self.course.location,
            data="Extra Tab", display_name="Extra Tab 3"
        )
        self.setup_user()
        self.enroll(self.course)
        self.user.is_staff = True
        self.relationship_types = get_milestone_relationship_types()
        self.addCleanup(set_current_request, None)

    def test_get_course_tabs_list_entrance_exam_enabled(self):
        """
        Unit Test: test_get_course_tabs_list_entrance_exam_enabled
        """
        entrance_exam = ItemFactory.create(
            category="chapter",
            parent_location=self.course.location,
            data="Exam Data",
            display_name="Entrance Exam",
            is_entrance_exam=True
        )
        milestone = {
            'name': 'Test Milestone',
            'namespace': '{}.entrance_exams'.format(unicode(self.course.id)),
            'description': 'Testing Courseware Tabs'
        }
        self.user.is_staff = False
        request = get_mock_request(self.user)
        self.course.entrance_exam_enabled = True
        self.course.entrance_exam_id = unicode(entrance_exam.location)
        milestone = add_milestone(milestone)
        add_course_milestone(
            unicode(self.course.id),
            self.relationship_types['REQUIRES'],
            milestone
        )
        add_course_content_milestone(
            unicode(self.course.id),
            unicode(entrance_exam.location),
            self.relationship_types['FULFILLS'],
            milestone
        )
        course_tab_list = get_course_tab_list(request, self.course)
        self.assertEqual(len(course_tab_list), 1)
        self.assertEqual(course_tab_list[0]['tab_id'], 'courseware')
        self.assertEqual(course_tab_list[0]['name'], 'Entrance Exam')

    def test_get_course_tabs_list_skipped_entrance_exam(self):
        """
        Tests tab list is not limited if user is allowed to skip entrance exam.
        """
        #create a user
        student = UserFactory()
        # login as instructor hit skip entrance exam api in instructor app
        instructor = InstructorFactory(course_key=self.course.id)
        self.client.logout()
        self.client.login(username=instructor.username, password='test')

        url = reverse('mark_student_can_skip_entrance_exam', kwargs={'course_id': unicode(self.course.id)})
        response = self.client.post(url, {
            'unique_student_identifier': student.email,
        })
        self.assertEqual(response.status_code, 200)

        # log in again as student
        self.client.logout()
        self.login(self.email, self.password)
        request = get_mock_request(self.user)
        course_tab_list = get_course_tab_list(request, self.course)
        self.assertEqual(len(course_tab_list), 4)

    def test_course_tabs_list_for_staff_members(self):
        """
        Tests tab list is not limited if user is member of staff
        and has not passed entrance exam.
        """
        # Login as member of staff
        self.client.logout()
        staff_user = StaffFactory(course_key=self.course.id)
        self.client.login(username=staff_user.username, password='test')
        request = get_mock_request(staff_user)
        course_tab_list = get_course_tab_list(request, self.course)
        self.assertEqual(len(course_tab_list), 4)


@attr(shard=1)
class TextBookCourseViewsTestCase(LoginEnrollmentTestCase, SharedModuleStoreTestCase):
    """
    Validate tab behavior when dealing with textbooks.
    """
    MODULESTORE = TEST_DATA_MIXED_MODULESTORE

    @classmethod
    def setUpClass(cls):
        super(TextBookCourseViewsTestCase, cls).setUpClass()
        cls.course = CourseFactory.create()

    def setUp(self):
        super(TextBookCourseViewsTestCase, self).setUp()

        self.set_up_books(2)
        self.setup_user()
        self.enroll(self.course)
        self.num_textbook_tabs = sum(1 for tab in self.course.tabs if tab.type in [
            'textbooks', 'pdf_textbooks', 'html_textbooks'
        ])
        self.num_textbooks = self.num_textbook_tabs * len(self.books)

    def set_up_books(self, num_books):
        """Initializes the textbooks in the course and adds the given number of books to each textbook"""
        self.books = [MagicMock() for _ in range(num_books)]
        for book_index, book in enumerate(self.books):
            book.title = 'Book{0}'.format(book_index)
        self.course.textbooks = self.books
        self.course.pdf_textbooks = self.books
        self.course.html_textbooks = self.books

    def test_pdf_textbook_tabs(self):
        """
        Test that all textbooks tab links generating correctly.
        """
        type_to_reverse_name = {'textbook': 'book', 'pdftextbook': 'pdf_book', 'htmltextbook': 'html_book'}
        self.addCleanup(set_current_request, None)
        request = get_mock_request(self.user)
        course_tab_list = get_course_tab_list(request, self.course)
        num_of_textbooks_found = 0
        for tab in course_tab_list:
            # Verify links of all textbook type tabs.
            if tab.type == 'single_textbook':
                book_type, book_index = tab.tab_id.split("/", 1)
                expected_link = reverse(
                    type_to_reverse_name[book_type],
                    args=[text_type(self.course.id), book_index]
                )
                tab_link = tab.link_func(self.course, reverse)
                self.assertEqual(tab_link, expected_link)
                num_of_textbooks_found += 1
        self.assertEqual(num_of_textbooks_found, self.num_textbooks)

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_TEXTBOOK": False})
    def test_textbooks_disabled(self):
        tab = xmodule_tabs.CourseTab.load('textbooks')
        self.assertFalse(tab.is_enabled(self.course, self.user))


class TabListTestCase(TabTestCase):
    """Base class for Test cases involving tab lists."""

    def setUp(self):
        super(TabListTestCase, self).setUp()

        # invalid tabs
        self.invalid_tabs = [
            # less than 2 tabs
            [{'type': CoursewareTab.type}],
            # missing course_info
            [{'type': CoursewareTab.type}, {'type': 'discussion', 'name': 'fake_name'}],
            [{'type': 'unknown_type'}],
            # incorrect order
            [{'type': 'discussion', 'name': 'fake_name'},
             {'type': CourseInfoTab.type, 'name': 'fake_name'}, {'type': CoursewareTab.type}],
        ]

        # tab types that should appear only once
        unique_tab_types = [
            CoursewareTab.type,
            CourseInfoTab.type,
            'textbooks',
            'pdf_textbooks',
            'html_textbooks',
        ]

        for unique_tab_type in unique_tab_types:
            self.invalid_tabs.append([
                {'type': CoursewareTab.type},
                {'type': CourseInfoTab.type, 'name': 'fake_name'},
                # add the unique tab multiple times
                {'type': unique_tab_type},
                {'type': unique_tab_type},
            ])

        # valid tabs
        self.valid_tabs = [
            # any empty list is valid because a default list of tabs will be
            # generated to replace the empty list.
            [],
            # all valid tabs
            [
                {'type': CoursewareTab.type},
                {'type': CourseInfoTab.type, 'name': 'fake_name'},
                {'type': 'discussion', 'name': 'fake_name'},
                {'type': ExternalLinkCourseTab.type, 'name': 'fake_name', 'link': 'fake_link'},
                {'type': ExternalLinkCourseTab.type, 'name': 'fake_name', 'link': 'fake_link'},
                {'type': 'textbooks'},
                {'type': 'pdf_textbooks'},
                {'type': 'html_textbooks'},
                {'type': ProgressTab.type, 'name': 'fake_name'},
                {'type': xmodule_tabs.StaticTab.type, 'name': 'fake_name', 'url_slug': 'schlug'},
                {'type': 'syllabus'},
            ],
            # with external discussion
            [
                {'type': CoursewareTab.type},
                {'type': CourseInfoTab.type, 'name': 'fake_name'},
                {'type': ExternalDiscussionCourseTab.type, 'name': 'fake_name', 'link': 'fake_link'}
            ],
        ]

        self.all_valid_tab_list = xmodule_tabs.CourseTabList().from_json(self.valid_tabs[1])


@attr(shard=1)
class ValidateTabsTestCase(TabListTestCase):
    """Test cases for validating tabs."""

    def test_validate_tabs(self):
        tab_list = xmodule_tabs.CourseTabList()
        for invalid_tab_list in self.invalid_tabs:
            with self.assertRaises(xmodule_tabs.InvalidTabsException):
                tab_list.from_json(invalid_tab_list)

        for valid_tab_list in self.valid_tabs:
            from_json_result = tab_list.from_json(valid_tab_list)
            self.assertEquals(len(from_json_result), len(valid_tab_list))

    def test_invalid_tab_type(self):
        """
        Verifies that having an unrecognized tab type does not cause
        the tabs to be undisplayable.
        """
        tab_list = xmodule_tabs.CourseTabList()
        self.assertEquals(
            len(tab_list.from_json([
                {'type': CoursewareTab.type},
                {'type': CourseInfoTab.type, 'name': 'fake_name'},
                {'type': 'no_such_type'}
            ])),
            2
        )


@attr(shard=1)
class CourseTabListTestCase(TabListTestCase):
    """Testing the generator method for iterating through displayable tabs"""

    def setUp(self):
        super(CourseTabListTestCase, self).setUp()
        self.addCleanup(set_current_request, None)

    def has_tab(self, tab_list, tab_type):
        """ Searches the given lab_list for a given tab_type. """
        for tab in tab_list:
            if tab.type == tab_type:
                return True
        return False

    def test_initialize_default_without_syllabus(self):
        self.course.tabs = []
        self.course.syllabus_present = False
        xmodule_tabs.CourseTabList.initialize_default(self.course)
        self.assertFalse(self.has_tab(self.course.tabs, 'syllabus'))

    def test_initialize_default_with_syllabus(self):
        self.course.tabs = []
        self.course.syllabus_present = True
        xmodule_tabs.CourseTabList.initialize_default(self.course)
        self.assertTrue(self.has_tab(self.course.tabs, 'syllabus'))

    def test_initialize_default_with_external_link(self):
        self.course.tabs = []
        self.course.discussion_link = "other_discussion_link"
        xmodule_tabs.CourseTabList.initialize_default(self.course)
        self.assertTrue(self.has_tab(self.course.tabs, 'external_discussion'))
        self.assertFalse(self.has_tab(self.course.tabs, 'discussion'))

    def test_initialize_default_without_external_link(self):
        self.course.tabs = []
        self.course.discussion_link = ""
        xmodule_tabs.CourseTabList.initialize_default(self.course)
        self.assertFalse(self.has_tab(self.course.tabs, 'external_discussion'))
        self.assertTrue(self.has_tab(self.course.tabs, 'discussion'))

    @patch.dict("django.conf.settings.FEATURES", {
        "ENABLE_TEXTBOOK": True,
        "ENABLE_DISCUSSION_SERVICE": True,
        "ENABLE_STUDENT_NOTES": True,
        "ENABLE_EDXNOTES": True,
    })
    def test_iterate_displayable(self):
        self.course.hide_progress_tab = False

        # create 1 book per textbook type
        self.set_up_books(1)

        # initialize the course tabs to a list of all valid tabs
        self.course.tabs = self.all_valid_tab_list

        # enumerate the tabs with no user
        expected = [tab.type for tab in
                    xmodule_tabs.CourseTabList.iterate_displayable(self.course, inline_collections=False)]
        actual = [tab.type for tab in self.course.tabs if tab.is_enabled(self.course, user=None)]
        assert actual == expected

        # enumerate the tabs with a staff user
        user = UserFactory(is_staff=True)
        CourseEnrollment.enroll(user, self.course.id)
        for i, tab in enumerate(xmodule_tabs.CourseTabList.iterate_displayable(self.course, user=user)):
            if getattr(tab, 'is_collection_item', False):
                # a collection item was found as a result of a collection tab
                self.assertTrue(getattr(self.course.tabs[i], 'is_collection', False))
            else:
                # all other tabs must match the expected type
                self.assertEquals(tab.type, self.course.tabs[i].type)

        # test including non-empty collections
        self.assertIn(
            {'type': 'html_textbooks'},
            list(xmodule_tabs.CourseTabList.iterate_displayable(self.course, inline_collections=False)),
        )

        # test not including empty collections
        self.course.html_textbooks = []
        self.assertNotIn(
            {'type': 'html_textbooks'},
            list(xmodule_tabs.CourseTabList.iterate_displayable(self.course, inline_collections=False)),
        )

    def test_get_tab_by_methods(self):
        """Tests the get_tab methods in CourseTabList"""
        self.course.tabs = self.all_valid_tab_list
        for tab in self.course.tabs:

            # get tab by type
            self.assertEquals(xmodule_tabs.CourseTabList.get_tab_by_type(self.course.tabs, tab.type), tab)

            # get tab by id
            self.assertEquals(xmodule_tabs.CourseTabList.get_tab_by_id(self.course.tabs, tab.tab_id), tab)

    def test_course_tabs_staff_only(self):
        """
        Tests the static tabs that available only for instructor
        """
        self.course.tabs.append(xmodule_tabs.CourseTab.load('static_tab', name='Static Tab Free',
                                                            url_slug='extra_tab_1',
                                                            course_staff_only=False))
        self.course.tabs.append(xmodule_tabs.CourseTab.load('static_tab', name='Static Tab Instructors Only',
                                                            url_slug='extra_tab_2',
                                                            course_staff_only=True))
        self.course.save()

        user = self.create_mock_user(is_staff=False, is_enrolled=True)
        self.addCleanup(set_current_request, None)
        request = get_mock_request(user)
        course_tab_list = get_course_tab_list(request, self.course)
        name_list = [x.name for x in course_tab_list]
        self.assertIn('Static Tab Free', name_list)
        self.assertNotIn('Static Tab Instructors Only', name_list)

        # Login as member of staff
        self.client.logout()
        staff_user = StaffFactory(course_key=self.course.id)
        self.client.login(username=staff_user.username, password='test')
        request = get_mock_request(staff_user)
        course_tab_list_staff = get_course_tab_list(request, self.course)
        name_list_staff = [x.name for x in course_tab_list_staff]
        self.assertIn('Static Tab Free', name_list_staff)
        self.assertIn('Static Tab Instructors Only', name_list_staff)


@attr(shard=1)
class ProgressTestCase(TabTestCase):
    """Test cases for Progress Tab."""

    def check_progress_tab(self):
        """Helper function for verifying the progress tab."""
        return self.check_tab(
            tab_class=ProgressTab,
            dict_tab={'type': ProgressTab.type, 'name': 'same'},
            expected_link=self.reverse('progress', args=[text_type(self.course.id)]),
            expected_tab_id=ProgressTab.type,
            invalid_dict_tab=None,
        )

    @patch('student.models.CourseEnrollment.is_enrolled')
    def test_progress(self, is_enrolled):
        is_enrolled.return_value = True
        self.course.hide_progress_tab = False
        tab = self.check_progress_tab()
        self.check_can_display_results(
            tab, for_staff_only=True, for_enrolled_users_only=True
        )

        self.course.hide_progress_tab = True
        self.check_progress_tab()
        self.check_can_display_results(
            tab, for_staff_only=True, for_enrolled_users_only=True, expected_value=False
        )


@attr(shard=1)
class StaticTabTestCase(TabTestCase):
    """Test cases for Static Tab."""

    def test_static_tab(self):

        url_slug = 'schmug'

        tab = self.check_tab(
            tab_class=xmodule_tabs.StaticTab,
            dict_tab={'type': xmodule_tabs.StaticTab.type, 'name': 'same', 'url_slug': url_slug},
            expected_link=self.reverse('static_tab', args=[text_type(self.course.id), url_slug]),
            expected_tab_id='static_tab_schmug',
            invalid_dict_tab=self.fake_dict_tab,
        )
        self.check_can_display_results(tab)
        self.check_get_and_set_method_for_key(tab, 'url_slug')


@attr(shard=1)
class CourseInfoTabTestCase(TabTestCase):
    """Test cases for the course info tab."""
    def setUp(self):
        self.user = self.create_mock_user()
        self.addCleanup(set_current_request, None)
        self.request = get_mock_request(self.user)

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=False)
    def test_default_tab(self):
        # Verify that the course info tab is the first tab
        tabs = get_course_tab_list(self.request, self.course)
        self.assertEqual(tabs[0].type, 'course_info')

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=True)
    def test_default_tab_for_new_course_experience(self):
        # Verify that the unified course experience hides the course info tab
        tabs = get_course_tab_list(self.request, self.course)
        self.assertEqual(tabs[0].type, 'courseware')

    # TODO: LEARNER-611 - remove once course_info is removed.
    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=True)
    def test_default_tab_for_displayable(self):
        tabs = xmodule_tabs.CourseTabList.iterate_displayable(self.course, self.user)
        for i, tab in enumerate(tabs):
            if i == 0:
                self.assertEqual(tab.type, 'course_info')


@attr(shard=1)
class DiscussionLinkTestCase(TabTestCase):
    """Test cases for discussion link tab."""

    def setUp(self):
        super(DiscussionLinkTestCase, self).setUp()

        self.tabs_with_discussion = [
            xmodule_tabs.CourseTab.load('discussion'),
        ]
        self.tabs_without_discussion = [
        ]

    @staticmethod
    def _reverse(course):
        """Custom reverse function"""
        def reverse_discussion_link(viewname, args):
            """reverse lookup for discussion link"""
            if viewname == "forum_form_discussion" and args == [unicode(course.id)]:
                return "default_discussion_link"
        return reverse_discussion_link

    def check_discussion(
            self, tab_list,
            expected_discussion_link,
            expected_can_display_value,
            discussion_link_in_course="",
            is_staff=True,
            is_enrolled=True,
    ):
        """Helper function to verify whether the discussion tab exists and can be displayed"""
        self.course.tabs = tab_list
        self.course.discussion_link = discussion_link_in_course
        discussion_tab = xmodule_tabs.CourseTabList.get_discussion(self.course)
        user = self.create_mock_user(is_staff=is_staff, is_enrolled=is_enrolled)
        with patch('student.models.CourseEnrollment.is_enrolled') as check_is_enrolled:
            check_is_enrolled.return_value = is_enrolled
            self.assertEquals(
                (
                    discussion_tab is not None and
                    self.is_tab_enabled(discussion_tab, self.course, user) and
                    (discussion_tab.link_func(self.course, self._reverse(self.course)) == expected_discussion_link)
                ),
                expected_can_display_value
            )

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_DISCUSSION_SERVICE": False})
    def test_explicit_discussion_link(self):
        """Test that setting discussion_link overrides everything else"""
        self.check_discussion(
            tab_list=self.tabs_with_discussion,
            discussion_link_in_course="other_discussion_link",
            expected_discussion_link="other_discussion_link",
            expected_can_display_value=True,
        )

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_DISCUSSION_SERVICE": False})
    def test_discussions_disabled(self):
        """Test that other cases return None with discussions disabled"""
        for tab_list in [[], self.tabs_with_discussion, self.tabs_without_discussion]:
            self.check_discussion(
                tab_list=tab_list,
                expected_discussion_link=not None,
                expected_can_display_value=False,
            )

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_DISCUSSION_SERVICE": True})
    def test_tabs_with_discussion(self):
        """Test a course with a discussion tab configured"""
        self.check_discussion(
            tab_list=self.tabs_with_discussion,
            expected_discussion_link="default_discussion_link",
            expected_can_display_value=True,
        )

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_DISCUSSION_SERVICE": True})
    def test_tabs_without_discussion(self):
        """Test a course with tabs configured but without a discussion tab"""
        self.check_discussion(
            tab_list=self.tabs_without_discussion,
            expected_discussion_link=not None,
            expected_can_display_value=False,
        )

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_DISCUSSION_SERVICE": True})
    def test_tabs_enrolled_or_staff(self):
        for is_enrolled, is_staff in [(True, False), (False, True)]:
            self.check_discussion(
                tab_list=self.tabs_with_discussion,
                expected_discussion_link="default_discussion_link",
                expected_can_display_value=True,
                is_enrolled=is_enrolled,
                is_staff=is_staff
            )

    @patch.dict("django.conf.settings.FEATURES", {"ENABLE_DISCUSSION_SERVICE": True})
    def test_tabs_not_enrolled_or_staff(self):
        is_enrolled = is_staff = False
        self.check_discussion(
            tab_list=self.tabs_with_discussion,
            expected_discussion_link="default_discussion_link",
            expected_can_display_value=False,
            is_enrolled=is_enrolled,
            is_staff=is_staff
        )
