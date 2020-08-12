"""
Single page performance tests for Studio.
"""
from bok_choy.web_app_test import with_cache

from common.test.acceptance.pages.common.auto_auth import AutoAuthPage
from common.test.acceptance.pages.studio.overview import CourseOutlinePage

from ..tests.helpers import AcceptanceTest


class StudioPagePerformanceTest(AcceptanceTest):
    """
    Base class to capture studio performance with HTTP Archives.

    To import courses for the bok choy tests, pass the --imports_dir=<course directory> argument to the paver command
    where <course directory> contains the (un-archived) courses to be imported.
    """
    course_org = 'edX'
    course_num = 'Open_DemoX'
    course_run = 'edx_demo_course'
    har_mode = 'explicit'

    def setUp(self):
        """
        Authenticate as staff so we can view and edit courses.
        """
        super(StudioPagePerformanceTest, self).setUp()
        AutoAuthPage(self.browser, staff=True).visit()

    def record_visit_outline(self):
        """
        Produce a HAR for loading the course outline page.
        """
        course_outline_page = CourseOutlinePage(self.browser, self.course_org, self.course_num, self.course_run)
        har_name = 'OutlinePage_{org}_{course}'.format(
            org=self.course_org,
            course=self.course_num
        )
        self.har_capturer.add_page(self.browser, har_name)
        course_outline_page.visit()
        self.har_capturer.save_har(self.browser, har_name)

    def record_visit_unit(self, section_title, subsection_title, unit_title):
        """
        Produce a HAR for loading a unit page.
        """
        course_outline_page = CourseOutlinePage(self.browser, self.course_org, self.course_num, self.course_run).visit()
        course_outline_unit = course_outline_page.section(section_title).subsection(subsection_title).expand_subsection().unit(unit_title)
        har_name = 'UnitPage_{org}_{course}'.format(
            org=self.course_org,
            course=self.course_num
        )
        self.har_capturer.add_page(self.browser, har_name)
        course_outline_unit.go_to()
        self.har_capturer.save_har(self.browser, har_name)


class StudioJusticePerformanceTest(StudioPagePerformanceTest):
    """
    Test performance on the HarvardX Justice course.
    """
    course_org = 'HarvardX'
    course_num = 'ER22x'
    course_run = '2013_Spring'

    @with_cache
    def test_visit_outline(self):
        """Record visiting the Justice course outline page"""
        self.record_visit_outline()

    @with_cache
    def test_visit_unit(self):
        """Record visiting a Justice unit page"""
        self.record_visit_unit(
            'Lecture 1 - Doing the Right Thing',
            'Discussion Prompt: Ethics of Torture',
            'Discussion Prompt: Ethics of Torture'
        )


class StudioPub101PerformanceTest(StudioPagePerformanceTest):
    """
    Test performance on Andy's PUB101 outline page.
    """
    course_org = 'AndyA'
    course_num = 'PUB101'
    course_run = 'PUB101'

    @with_cache
    def test_visit_outline(self):
        """Record visiting the PUB101 course outline page"""
        self.record_visit_outline()

    @with_cache
    def test_visit_unit(self):
        """Record visiting the PUB101 unit page"""
        self.record_visit_unit('Released', 'Released', 'Released')
