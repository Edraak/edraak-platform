"""
Course discovery page.
"""

from bok_choy.page_object import PageObject

from common.test.acceptance.pages.lms import BASE_URL


class CourseDiscoveryPage(PageObject):
    """
    Find courses page (main page of the LMS).
    """

    url = BASE_URL + "/courses"
    form = "#discovery-form"

    def is_browser_on_page(self):
        """
        Loading indicator must be present, but not visible
        """
        loading_css = "#loading-indicator"
        courses_css = '.courses-listing'

        return self.q(css=courses_css).visible \
            and self.q(css=loading_css).present \
            and not self.q(css=loading_css).visible

    @property
    def result_items(self):
        """
        Return search result items.
        """
        return self.q(css=".courses-list .courses-listing-item")

    @property
    def clear_button(self):
        """
        Clear all button.
        """
        return self.q(css="#clear-all-filters")

    def search(self, string):
        """
        Search and wait for ajax.
        """
        self.q(css=self.form + ' input[type="text"]').fill(string)
        self.q(css=self.form + ' [type="submit"]').click()
        self.wait_for_ajax()

    def clear_search(self):
        """
        Clear search results.
        """
        self.clear_button.click()
        self.wait_for_ajax()

    def click_course(self, course_id):
        """
        Click on the course

        Args:
            course_id(string): ID of the course which is to be clicked
        """
        self.q(css='.courses-listing-item a').filter(lambda el: course_id in el.get_attribute('href')).click()
