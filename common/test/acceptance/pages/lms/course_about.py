"""
Course about page (with registration button)
"""

from common.test.acceptance.pages.lms.course_page import CoursePage
from common.test.acceptance.pages.lms.login_and_register import RegisterPage


class CourseAboutPage(CoursePage):
    """
    Course about page (with registration button)
    """

    url_path = "about"

    def is_browser_on_page(self):
        return self.q(css='section.course-info').present

    def register(self):
        """
        Navigate to the registration page.
        Waits for the registration page to load, then
        returns the registration page object.
        """
        self.q(css='a.register').first.click()

        registration_page = RegisterPage(self.browser, self.course_id)
        registration_page.wait_for_page()
        return registration_page

    def enroll_in_course(self):
        """
        Click on enroll button
        """
        self.wait_for_element_visibility('.register', 'Enroll button is present')
        self.q(css='.register').first.click()
