"""
Test the about xblock
"""
import datetime
import ddt
import mock
import pytz
from ccx_keys.locator import CCXLocator
from django.conf import settings
from django.urls import reverse
from django.test.utils import override_settings
from milestones.tests.utils import MilestonesTestCaseMixin
from mock import patch
from six import text_type
from waffle.testutils import override_switch

from course_modes.models import CourseMode
from lms.djangoapps.ccx.tests.factories import CcxFactory
from openedx.core.lib.tests import attr
from openedx.core.djangoapps.waffle_utils.testutils import override_waffle_flag
from openedx.features.course_experience.waffle import WAFFLE_NAMESPACE as COURSE_EXPERIENCE_WAFFLE_NAMESPACE
from openedx.features.course_experience.waffle import ENABLE_COURSE_ABOUT_SIDEBAR_HTML
from openedx.features.course_experience import COURSE_ENABLE_UNENROLLED_ACCESS_FLAG
from shoppingcart.models import Order, PaidCourseRegistration
from student.models import CourseEnrollment
from student.tests.factories import AdminFactory, CourseEnrollmentAllowedFactory, UserFactory
from track.tests import EventTrackingTestCase
from util.milestones_helpers import get_prerequisite_courses_display, set_prerequisite_courses
from xmodule.course_module import (
    CATALOG_VISIBILITY_ABOUT,
    CATALOG_VISIBILITY_NONE,
    COURSE_VISIBILITY_PRIVATE,
    COURSE_VISIBILITY_PUBLIC_OUTLINE,
    COURSE_VISIBILITY_PUBLIC
)
from xmodule.modulestore.tests.django_utils import (
    TEST_DATA_MIXED_MODULESTORE,
    TEST_DATA_SPLIT_MODULESTORE,
    ModuleStoreTestCase,
    SharedModuleStoreTestCase
)
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore.tests.utils import TEST_DATA_DIR
from xmodule.modulestore.xml_importer import import_course_from_xml

from .helpers import LoginEnrollmentTestCase

# HTML for registration button
REG_STR = "<form id=\"class_enroll_form\" method=\"post\" data-remote=\"true\" action=\"/change_enrollment\">"
SHIB_ERROR_STR = "The currently logged-in user account does not have permission to enroll in this course."


@ddt.ddt
@attr(shard=1)
class AboutTestCase(LoginEnrollmentTestCase, SharedModuleStoreTestCase, EventTrackingTestCase, MilestonesTestCaseMixin):
    """
    Tests about xblock.
    """

    @classmethod
    def setUpClass(cls):
        super(AboutTestCase, cls).setUpClass()
        cls.course = CourseFactory.create()
        cls.course_without_about = CourseFactory.create(catalog_visibility=CATALOG_VISIBILITY_NONE)
        cls.course_with_about = CourseFactory.create(catalog_visibility=CATALOG_VISIBILITY_ABOUT)
        cls.purchase_course = CourseFactory.create(org='MITx', number='buyme', display_name='Course To Buy')
        cls.about = ItemFactory.create(
            category="about", parent_location=cls.course.location,
            data="OOGIE BLOOGIE", display_name="overview"
        )
        cls.about = ItemFactory.create(
            category="about", parent_location=cls.course_without_about.location,
            data="WITHOUT ABOUT", display_name="overview"
        )
        cls.about = ItemFactory.create(
            category="about", parent_location=cls.course_with_about.location,
            data="WITH ABOUT", display_name="overview"
        )

    def setUp(self):
        super(AboutTestCase, self).setUp()

        self.course_mode = CourseMode(
            course_id=self.purchase_course.id,
            mode_slug=CourseMode.DEFAULT_MODE_SLUG,
            mode_display_name=CourseMode.DEFAULT_MODE_SLUG,
            min_price=10
        )
        self.course_mode.save()

    def test_anonymous_user(self):
        """
        This test asserts that a non-logged in user can visit the course about page
        """
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)

        # Check that registration button is present
        self.assertIn(REG_STR, resp.content)

    def test_logged_in(self):
        """
        This test asserts that a logged-in user can visit the course about page
        """
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)

    def test_already_enrolled(self):
        """
        Asserts that the end user sees the appropriate messaging
        when he/she visits the course about page, but is already enrolled
        """
        self.setup_user()
        self.enroll(self.course, True)
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("You are enrolled in this course", resp.content)
        self.assertIn("View Course", resp.content)

    @override_settings(COURSE_ABOUT_VISIBILITY_PERMISSION="see_about_page")
    def test_visible_about_page_settings(self):
        """
        Verify that the About Page honors the permission settings in the course module
        """
        url = reverse('about_course', args=[text_type(self.course_with_about.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("WITH ABOUT", resp.content)

        url = reverse('about_course', args=[text_type(self.course_without_about.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_SITE': True})
    def test_logged_in_marketing(self):
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        # should be redirected
        self.assertEqual(resp.status_code, 302)
        # follow this time, and check we're redirected to the course home page
        resp = self.client.get(url, follow=True)
        target_url = resp.redirect_chain[-1][0]
        course_home_url = reverse('openedx.course_experience.course_home', args=[text_type(self.course.id)])
        self.assertTrue(target_url.endswith(course_home_url))

    @patch.dict(settings.FEATURES, {'ENABLE_COURSE_HOME_REDIRECT': False})
    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_SITE': True})
    def test_logged_in_marketing_without_course_home_redirect(self):
        """
        Verify user is not redirected to course home page when
        ENABLE_COURSE_HOME_REDIRECT is set to False
        """
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        # should not be redirected
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)

    @patch.dict(settings.FEATURES, {'ENABLE_COURSE_HOME_REDIRECT': True})
    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_SITE': False})
    def test_logged_in_marketing_without_mktg_site(self):
        """
        Verify user is not redirected to course home page when
        ENABLE_MKTG_SITE is set to False
        """
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        # should not be redirected
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)

    @patch.dict(settings.FEATURES, {'ENABLE_PREREQUISITE_COURSES': True})
    def test_pre_requisite_course(self):
        pre_requisite_course = CourseFactory.create(org='edX', course='900', display_name='pre requisite course')
        course = CourseFactory.create(pre_requisite_courses=[text_type(pre_requisite_course.id)])
        self.setup_user()
        url = reverse('about_course', args=[text_type(course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        pre_requisite_courses = get_prerequisite_courses_display(course)
        pre_requisite_course_about_url = reverse('about_course', args=[text_type(pre_requisite_courses[0]['key'])])
        self.assertIn("<span class=\"important-dates-item-text pre-requisite\"><a href=\"{}\">{}</a></span>"
                      .format(pre_requisite_course_about_url, pre_requisite_courses[0]['display']),
                      resp.content.strip('\n'))

    @patch.dict(settings.FEATURES, {'ENABLE_PREREQUISITE_COURSES': True})
    def test_about_page_unfulfilled_prereqs(self):
        pre_requisite_course = CourseFactory.create(
            org='edX',
            course='901',
            display_name='pre requisite course',
        )

        pre_requisite_courses = [text_type(pre_requisite_course.id)]

        # for this failure to occur, the enrollment window needs to be in the past
        course = CourseFactory.create(
            org='edX',
            course='1000',
            # closed enrollment
            enrollment_start=datetime.datetime(2013, 1, 1),
            enrollment_end=datetime.datetime(2014, 1, 1),
            start=datetime.datetime(2013, 1, 1),
            end=datetime.datetime(2030, 1, 1),
            pre_requisite_courses=pre_requisite_courses,
        )
        set_prerequisite_courses(course.id, pre_requisite_courses)

        self.setup_user()
        self.enroll(self.course, True)
        self.enroll(pre_requisite_course, True)

        url = reverse('about_course', args=[text_type(course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        pre_requisite_courses = get_prerequisite_courses_display(course)
        pre_requisite_course_about_url = reverse('about_course', args=[text_type(pre_requisite_courses[0]['key'])])
        self.assertIn("<span class=\"important-dates-item-text pre-requisite\"><a href=\"{}\">{}</a></span>"
                      .format(pre_requisite_course_about_url, pre_requisite_courses[0]['display']),
                      resp.content.strip('\n'))

        url = reverse('about_course', args=[unicode(pre_requisite_course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    @ddt.data(
        [COURSE_VISIBILITY_PRIVATE],
        [COURSE_VISIBILITY_PUBLIC_OUTLINE],
        [COURSE_VISIBILITY_PUBLIC],
    )
    @ddt.unpack
    def test_about_page_public_view(self, course_visibility):
        """
        Assert that anonymous or unenrolled users see View Course option
        when unenrolled access flag is set
        """
        with mock.patch('xmodule.course_module.CourseDescriptor.course_visibility', course_visibility):
            with override_waffle_flag(COURSE_ENABLE_UNENROLLED_ACCESS_FLAG, active=True):
                url = reverse('about_course', args=[text_type(self.course.id)])
                resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        if course_visibility == COURSE_VISIBILITY_PUBLIC or course_visibility == COURSE_VISIBILITY_PUBLIC_OUTLINE:
            self.assertIn("View Course", resp.content)
        else:
            self.assertIn("Enroll in", resp.content)


@attr(shard=1)
class AboutTestCaseXML(LoginEnrollmentTestCase, ModuleStoreTestCase):
    """
    Tests for the course about page
    """
    MODULESTORE = TEST_DATA_MIXED_MODULESTORE

    def setUp(self):
        """
        Set up the tests
        """
        super(AboutTestCaseXML, self).setUp()

        # The following test course (which lives at common/test/data/2014)
        # is closed; we're testing that an about page still appears when
        # the course is already closed
        self.xml_course_id = self.store.make_course_key('edX', 'detached_pages', '2014')
        import_course_from_xml(
            self.store,
            'test_user',
            TEST_DATA_DIR,
            source_dirs=['2014'],
            static_content_store=None,
            target_id=self.xml_course_id,
            raise_on_failure=True,
            create_if_not_present=True,
        )

        # this text appears in that course's about page
        # common/test/data/2014/about/overview.html
        self.xml_data = "about page 463139"

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_logged_in_xml(self):
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.xml_course_id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.xml_data, resp.content)

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_anonymous_user_xml(self):
        url = reverse('about_course', args=[text_type(self.xml_course_id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.xml_data, resp.content)


@attr(shard=1)
class AboutWithCappedEnrollmentsTestCase(LoginEnrollmentTestCase, SharedModuleStoreTestCase):
    """
    This test case will check the About page when a course has a capped enrollment
    """
    @classmethod
    def setUpClass(cls):
        super(AboutWithCappedEnrollmentsTestCase, cls).setUpClass()
        cls.course = CourseFactory.create(metadata={"max_student_enrollments_allowed": 1})
        cls.about = ItemFactory.create(
            category="about", parent_location=cls.course.location,
            data="OOGIE BLOOGIE", display_name="overview"
        )

    def test_enrollment_cap(self):
        """
        This test will make sure that enrollment caps are enforced
        """
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<a href="#" class="register">', resp.content)

        self.enroll(self.course, verify=True)

        # create a new account since the first account is already enrolled in the course
        self.email = 'foo_second@test.com'
        self.password = 'bar'
        self.username = 'test_second'
        self.create_account(self.username, self.email, self.password)
        self.activate_user(self.email)
        self.login(self.email, self.password)

        # Get the about page again and make sure that the page says that the course is full
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Course is full", resp.content)

        # Try to enroll as well
        result = self.enroll(self.course)
        self.assertFalse(result)

        # Check that registration button is not present
        self.assertNotIn(REG_STR, resp.content)


@attr(shard=1)
class AboutWithInvitationOnly(SharedModuleStoreTestCase):
    """
    This test case will check the About page when a course is invitation only.
    """
    @classmethod
    def setUpClass(cls):
        super(AboutWithInvitationOnly, cls).setUpClass()
        cls.course = CourseFactory.create(metadata={"invitation_only": True})
        cls.about = ItemFactory.create(
            category="about", parent_location=cls.course.location,
            display_name="overview"
        )

    def test_invitation_only(self):
        """
        Test for user not logged in, invitation only course.
        """

        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Enrollment in this course is by invitation only", resp.content)

        # Check that registration button is not present
        self.assertNotIn(REG_STR, resp.content)

    def test_invitation_only_but_allowed(self):
        """
        Test for user logged in and allowed to enroll in invitation only course.
        """

        # Course is invitation only, student is allowed to enroll and logged in
        user = UserFactory.create(username='allowed_student', password='test', email='allowed_student@test.com')
        CourseEnrollmentAllowedFactory(email=user.email, course_id=self.course.id)
        self.client.login(username=user.username, password='test')

        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(u"Enroll in {}".format(self.course.id.course), resp.content.decode('utf-8'))

        # Check that registration button is present
        self.assertIn(REG_STR, resp.content)


@attr(shard=1)
@patch.dict(settings.FEATURES, {'RESTRICT_ENROLL_BY_REG_METHOD': True})
class AboutTestCaseShibCourse(LoginEnrollmentTestCase, SharedModuleStoreTestCase):
    """
    Test cases covering about page behavior for courses that use shib enrollment domain ("shib courses")
    """
    @classmethod
    def setUpClass(cls):
        super(AboutTestCaseShibCourse, cls).setUpClass()
        cls.course = CourseFactory.create(enrollment_domain="shib:https://idp.stanford.edu/")
        cls.about = ItemFactory.create(
            category="about", parent_location=cls.course.location,
            data="OOGIE BLOOGIE", display_name="overview"
        )

    def test_logged_in_shib_course(self):
        """
        For shib courses, logged in users will see the enroll button, but get rejected once they click there
        """
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)
        self.assertIn(u"Enroll in {}".format(self.course.id.course), resp.content.decode('utf-8'))
        self.assertIn(SHIB_ERROR_STR, resp.content)
        self.assertIn(REG_STR, resp.content)

    def test_anonymous_user_shib_course(self):
        """
        For shib courses, anonymous users will also see the enroll button
        """
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OOGIE BLOOGIE", resp.content)
        self.assertIn(u"Enroll in {}".format(self.course.id.course), resp.content.decode('utf-8'))
        self.assertIn(SHIB_ERROR_STR, resp.content)
        self.assertIn(REG_STR, resp.content)


@attr(shard=1)
class AboutWithClosedEnrollment(ModuleStoreTestCase):
    """
    This test case will check the About page for a course that has enrollment start/end
    set but it is currently outside of that period.
    """
    def setUp(self):
        super(AboutWithClosedEnrollment, self).setUp()

        self.course = CourseFactory.create(metadata={"invitation_only": False})

        # Setup enrollment period to be in future
        now = datetime.datetime.now(pytz.UTC)
        tomorrow = now + datetime.timedelta(days=1)
        nextday = tomorrow + datetime.timedelta(days=1)

        self.course.enrollment_start = tomorrow
        self.course.enrollment_end = nextday
        self.course = self.update_course(self.course, self.user.id)

        self.about = ItemFactory.create(
            category="about", parent_location=self.course.location,
            display_name="overview"
        )

    def test_closed_enrollmement(self):
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Enrollment is Closed", resp.content)

        # Check that registration button is not present
        self.assertNotIn(REG_STR, resp.content)

    def test_course_price_is_not_visble_in_sidebar(self):
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # course price is not visible ihe course_about page when the course
        # mode is not set to honor
        self.assertNotIn('<span class="important-dates-item-text">$10</span>', resp.content)


@attr(shard=1)
@ddt.ddt
class AboutSidebarHTMLTestCase(SharedModuleStoreTestCase):
    """
    This test case will check the About page for the content in the HTML sidebar.
    """
    def setUp(self):
        super(AboutSidebarHTMLTestCase, self).setUp()
        self.course = CourseFactory.create()

    @ddt.data(
        ("", "", False),
        ("about_sidebar_html", "About Sidebar HTML Heading", False),
        ("about_sidebar_html", "", False),
        ("", "", True),
        ("about_sidebar_html", "About Sidebar HTML Heading", True),
        ("about_sidebar_html", "", True),
    )
    @ddt.unpack
    def test_html_sidebar_enabled(self, itemfactory_display_name, itemfactory_data, waffle_switch_value):
        with override_switch(
            '{}.{}'.format(
                COURSE_EXPERIENCE_WAFFLE_NAMESPACE,
                ENABLE_COURSE_ABOUT_SIDEBAR_HTML
            ),
            active=waffle_switch_value
        ):
            if itemfactory_display_name:
                ItemFactory.create(
                    category="about",
                    parent_location=self.course.location,
                    display_name=itemfactory_display_name,
                    data=itemfactory_data,
                )
            url = reverse('about_course', args=[text_type(self.course.id)])
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            if waffle_switch_value and itemfactory_display_name and itemfactory_data:
                self.assertIn('<section class="about-sidebar-html">', resp.content)
                self.assertIn(itemfactory_data, resp.content)
            else:
                self.assertNotIn('<section class="about-sidebar-html">', resp.content)


@attr(shard=1)
@patch.dict(settings.FEATURES, {'ENABLE_SHOPPING_CART': True})
@patch.dict(settings.FEATURES, {'ENABLE_PAID_COURSE_REGISTRATION': True})
class AboutPurchaseCourseTestCase(LoginEnrollmentTestCase, SharedModuleStoreTestCase):
    """
    This test class runs through a suite of verifications regarding
    purchaseable courses
    """
    @classmethod
    def setUpClass(cls):
        super(AboutPurchaseCourseTestCase, cls).setUpClass()
        cls.course = CourseFactory.create(org='MITx', number='buyme', display_name='Course To Buy')

        now = datetime.datetime.now(pytz.UTC)
        tomorrow = now + datetime.timedelta(days=1)
        nextday = tomorrow + datetime.timedelta(days=1)

        cls.closed_course = CourseFactory.create(
            org='MITx',
            number='closed',
            display_name='Closed Course To Buy',
            enrollment_start=tomorrow,
            enrollment_end=nextday
        )

    def setUp(self):
        super(AboutPurchaseCourseTestCase, self).setUp()
        self._set_ecomm(self.course)
        self._set_ecomm(self.closed_course)

    def _set_ecomm(self, course):
        """
        Helper method to turn on ecommerce on the course
        """
        course_mode = CourseMode(
            course_id=course.id,
            mode_slug=CourseMode.DEFAULT_MODE_SLUG,
            mode_display_name=CourseMode.DEFAULT_MODE_SLUG,
            min_price=10,
        )
        course_mode.save()

    def test_anonymous_user(self):
        """
        Make sure an anonymous user sees the purchase button
        """
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Add buyme to Cart <span>($10 USD)</span>", resp.content)

    def test_logged_in(self):
        """
        Make sure a logged in user sees the purchase button
        """
        self.setup_user()
        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Add buyme to Cart <span>($10 USD)</span>", resp.content)

    def test_already_in_cart(self):
        """
        This makes sure if a user has this course in the cart, that the expected message
        appears
        """
        self.setup_user()
        cart = Order.get_cart_for_user(self.user)
        PaidCourseRegistration.add_to_order(cart, self.course.id)

        url = reverse('about_course', args=[text_type(self.course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("This course is in your", resp.content)
        self.assertNotIn("Add buyme to Cart <span>($10 USD)</span>", resp.content)

    def test_already_enrolled(self):
        """
        This makes sure that the already enrolled message appears for paywalled courses
        """
        self.setup_user()

        # note that we can't call self.enroll here since that goes through
        # the Django student views, which doesn't allow for enrollments
        # for paywalled courses
        CourseEnrollment.enroll(self.user, self.course.id)

        url = reverse('about_course', args=[text_type(self.course.id)])

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("You are enrolled in this course", resp.content)
        self.assertIn("View Course", resp.content)
        self.assertNotIn("Add buyme to Cart <span>($10 USD)</span>", resp.content)

    def test_closed_enrollment(self):
        """
        This makes sure that paywalled courses also honor the registration
        window
        """
        self.setup_user()

        url = reverse('about_course', args=[text_type(self.closed_course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Enrollment is Closed", resp.content)
        self.assertNotIn("Add closed to Cart <span>($10 USD)</span>", resp.content)

        # course price is visible ihe course_about page when the course
        # mode is set to honor and it's price is set
        self.assertIn('<span class="important-dates-item-text">$10</span>', resp.content)

    def test_invitation_only(self):
        """
        This makes sure that the invitation only restirction takes prescendence over
        any purchase enablements
        """
        course = CourseFactory.create(metadata={"invitation_only": True})
        self._set_ecomm(course)
        self.setup_user()

        url = reverse('about_course', args=[text_type(course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Enrollment in this course is by invitation only", resp.content)

    def test_enrollment_cap(self):
        """
        Make sure that capped enrollments work even with
        paywalled courses
        """
        course = CourseFactory.create(
            metadata={
                "max_student_enrollments_allowed": 1,
                "display_coursenumber": "buyme",
            }
        )
        self._set_ecomm(course)

        self.setup_user()
        url = reverse('about_course', args=[text_type(course.id)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Add buyme to Cart <span>($10 USD)</span>", resp.content)

        # note that we can't call self.enroll here since that goes through
        # the Django student views, which doesn't allow for enrollments
        # for paywalled courses
        CourseEnrollment.enroll(self.user, course.id)

        # create a new account since the first account is already enrolled in the course
        email = 'foo_second@test.com'
        password = 'bar'
        username = 'test_second'
        self.create_account(username,
                            email, password)
        self.activate_user(email)
        self.login(email, password)

        # Get the about page again and make sure that the page says that the course is full
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Course is full", resp.content)
        self.assertNotIn("Add buyme to Cart ($10)", resp.content)

    def test_free_course_display(self):
        """
        Make sure other courses that don't have shopping cart enabled don't display the add-to-cart button
        and don't display the course_price field if Cosmetic Price is disabled.
        """
        course = CourseFactory.create(org='MITx', number='free', display_name='Course For Free')
        self.setup_user()
        url = reverse('about_course', args=[text_type(course.id)])

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Add free to Cart (Free)", resp.content)
        self.assertNotIn('<p class="important-dates-item-title">Price</p>', resp.content)


class CourseAboutTestCaseCCX(SharedModuleStoreTestCase, LoginEnrollmentTestCase):
    """
    Test for unenrolled student tries to access ccx.
    Note: Only CCX coach can enroll a student in CCX. In sum self-registration not allowed.
    """
    MODULESTORE = TEST_DATA_SPLIT_MODULESTORE

    @classmethod
    def setUpClass(cls):
        super(CourseAboutTestCaseCCX, cls).setUpClass()
        cls.course = CourseFactory.create()

    def setUp(self):
        super(CourseAboutTestCaseCCX, self).setUp()

        # Create ccx coach account
        self.coach = coach = AdminFactory.create(password="test")
        self.client.login(username=coach.username, password="test")

    def test_redirect_to_dashboard_unenrolled_ccx(self):
        """
        Assert that when unenrolled user tries to access CCX do not allow the user to self-register.
        Redirect him to his student dashboard
        """

        # create ccx
        ccx = CcxFactory(course_id=self.course.id, coach=self.coach)
        ccx_locator = CCXLocator.from_course_locator(self.course.id, unicode(ccx.id))

        self.setup_user()
        url = reverse('openedx.course_experience.course_home', args=[ccx_locator])
        response = self.client.get(url)
        expected = reverse('dashboard')
        self.assertRedirects(response, expected, status_code=302, target_status_code=200)
