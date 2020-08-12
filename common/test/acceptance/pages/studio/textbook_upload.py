"""
Course Textbooks page.
"""

import requests
from path import Path as path

from common.test.acceptance.pages.common.utils import click_css
from common.test.acceptance.pages.studio.course_page import CoursePage


class TextbookUploadPage(CoursePage):
    """
    Course Textbooks page.
    """

    url_path = "textbooks"

    def is_browser_on_page(self):
        return self.q(css='.textbooks-list').visible

    def open_add_textbook_form(self):
        """
        Open new textbook form by clicking on new textbook button.
        """
        self.q(css='.nav-item .new-button').click()

    def get_element_text(self, selector):
        """
        Return the text of the css selector.
        """
        return self.q(css=selector)[0].text

    def set_input_field_value(self, selector, value):
        """
        Set the value of input field by selector.
        """
        self.q(css=selector)[0].send_keys(value)

    def upload_pdf_file(self, file_name):
        """
        Uploads a pdf textbook.
        """
        # If the pdf upload section has not yet been toggled on, click on the upload pdf button
        test_dir = path(__file__).abspath().dirname().dirname().dirname().dirname()  # pylint:disable=no-value-for-parameter
        file_path = test_dir + '/data/uploads/' + file_name

        click_css(self, ".edit-textbook .action-upload", require_notification=False)
        self.wait_for_element_visibility(".upload-dialog input", "Upload modal opened")
        file_input = self.q(css=".upload-dialog input").results[0]
        file_input.send_keys(file_path)
        click_css(self, ".wrapper-modal-window-assetupload .action-upload", require_notification=False)
        self.wait_for_element_absence(".modal-window-overlay", "Upload modal closed")

    def click_textbook_submit_button(self):
        """
        Submit the new textbook form and check if it is rendered properly.
        """
        self.wait_for_element_visibility('#edit_textbook_form button[type="submit"]', 'Save button visibility')
        self.q(css='#edit_textbook_form button[type="submit"]').first.click()
        self.wait_for_element_absence(".wrapper-form", "Add/Edit form closed")

    def is_view_live_link_worked(self):
        """
        Check if the view live button of textbook is working fine.
        """
        try:
            self.wait_for(lambda: len(self.q(css='.textbook a.view').attrs('href')) > 0, "href value present")
            response = requests.get(self.q(css='.textbook a.view').attrs('href')[0])
        except requests.exceptions.ConnectionError:
            return False

        return response.status_code == 200

    def upload_new_textbook(self):
        """
        Fills out form to upload a new textbook
        """
        self.open_add_textbook_form()
        self.upload_pdf_file('textbook.pdf')
        self.set_input_field_value('.edit-textbook #textbook-name-input', 'book_1')
        self.set_input_field_value('.edit-textbook #chapter1-name', 'chap_1')
        self.click_textbook_submit_button()

    def set_textbook_name(self, textbook_name):
        """
        Set the name of textbook.
        """
        self.open_add_textbook_form()
        self.set_input_field_value('.edit-textbook #textbook-name-input', textbook_name)

    def fill_chapter_name(self, ordinal, chapter_name):
        """
        Adds chapter name by taking the ordinal of the chapter.
        """
        index = ["first", "second", "third"].index(ordinal)
        self.set_input_field_value('.textbook .chapter{i} input.chapter-name'.format(i=index + 1), chapter_name)

    def fill_chapter_asset(self, ordinal, chapter_asset):
        """
        Adds chapter asset by taking the ordinal of the chapter.
        """
        index = ["first", "second", "third"].index(ordinal)
        self.set_input_field_value('.textbook .chapter{i} input.chapter-asset-path'.format(i=index + 1), chapter_asset)

    def submit_chapter(self):
        """
        Click on Add Chapter button.
        """
        self.q(css='.action.action-add-chapter').first.click()

    @property
    def textbook_name(self):
        """
        Gets the name of a saved textbook.
        """
        return self.q(css='.textbook-title').text[0]

    def get_chapter_name(self, index):
        """
        Gets the name of chapter by taking an ordinal.
        """
        return self.q(css='.chapter-name').text[index]

    def get_asset_name(self, index):
        """
        Gets the name of chapter asset by taking an ordinal.
        """
        return self.q(css='.chapter-asset-path').text[index]

    def toggle_chapters(self):
        """
        Toggle saved chapters.
        """
        self.q(css='.chapter-toggle.show-chapters').click()

    @property
    def number_of_chapters(self):
        """
        Gets the total number of saved chapters.
        """
        return len(self.q(css='.chapter').results)

    def refresh_and_wait_for_load(self):
        """
        Refresh the page and wait for all resources to load.
        """
        self.browser.refresh()
        self.wait_for_page()
