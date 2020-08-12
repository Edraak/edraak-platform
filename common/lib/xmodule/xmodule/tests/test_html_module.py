import unittest
from mock import Mock
import ddt

from django.test.utils import override_settings

from opaque_keys.edx.locator import CourseLocator
from xblock.field_data import DictFieldData
from xblock.fields import ScopeIds

from xmodule.html_module import CourseInfoModule, HtmlDescriptor, HtmlModule

from . import get_test_descriptor_system, get_test_system
from ..x_module import PUBLIC_VIEW, STUDENT_VIEW


def instantiate_descriptor(**field_data):
    """
    Instantiate descriptor with most properties.
    """
    system = get_test_descriptor_system()
    course_key = CourseLocator('org', 'course', 'run')
    usage_key = course_key.make_usage_key('html', 'SampleHtml')
    return system.construct_xblock_from_class(
        HtmlDescriptor,
        scope_ids=ScopeIds(None, None, usage_key, usage_key),
        field_data=DictFieldData(field_data),
    )


@ddt.ddt
class HtmlModuleCourseApiTestCase(unittest.TestCase):
    """
    Test the HTML XModule's student_view_data method.
    """
    shard = 1

    @ddt.data(
        dict(),
        dict(FEATURES={}),
        dict(FEATURES=dict(ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA=False))
    )
    def test_disabled(self, settings):
        """
        Ensure that student_view_data does not return html if the ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA feature flag
        is not set.
        """
        descriptor = Mock()
        field_data = DictFieldData({'data': '<h1>Some HTML</h1>'})
        module_system = get_test_system()
        module = HtmlModule(descriptor, module_system, field_data, Mock())

        with override_settings(**settings):
            self.assertEqual(module.student_view_data(), dict(
                enabled=False,
                message='To enable, set FEATURES["ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA"]',
            ))

    @ddt.data(
        '<h1>Some content</h1>',  # Valid HTML
        '',
        None,
        '<h1>Some content</h',  # Invalid HTML
        '<script>alert()</script>',  # Does not escape tags
        '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">',  # Images allowed
        'short string ' * 100,  # May contain long strings
    )
    @override_settings(FEATURES=dict(ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA=True))
    def test_common_values(self, html):
        """
        Ensure that student_view_data will return HTML data when enabled,
        can handle likely input,
        and doesn't modify the HTML in any way.

        This means that it does NOT protect against XSS, escape HTML tags, etc.

        Note that the %%USER_ID%% substitution is tested below.
        """
        descriptor = Mock()
        field_data = DictFieldData({'data': html})
        module_system = get_test_system()
        module = HtmlModule(descriptor, module_system, field_data, Mock())
        self.assertEqual(module.student_view_data(), dict(enabled=True, html=html))

    @ddt.data(
        STUDENT_VIEW,
        PUBLIC_VIEW,
    )
    def test_student_preview_view(self, view):
        """
        Ensure that student_view and public_view renders correctly.
        """
        html = '<p>This is a test</p>'
        descriptor = Mock()
        field_data = DictFieldData({'data': html})
        module_system = get_test_system()
        module = HtmlModule(descriptor, module_system, field_data, Mock())
        rendered = module_system.render(module, view, {}).content
        self.assertIn(html, rendered)


class HtmlModuleSubstitutionTestCase(unittest.TestCase):
    descriptor = Mock()
    shard = 1

    def test_substitution_works(self):
        sample_xml = '''%%USER_ID%%'''
        field_data = DictFieldData({'data': sample_xml})
        module_system = get_test_system()
        module = HtmlModule(self.descriptor, module_system, field_data, Mock())
        self.assertEqual(module.get_html(), str(module_system.anonymous_student_id))

    def test_substitution_without_magic_string(self):
        sample_xml = '''
            <html>
                <p>Hi USER_ID!11!</p>
            </html>
        '''
        field_data = DictFieldData({'data': sample_xml})
        module_system = get_test_system()
        module = HtmlModule(self.descriptor, module_system, field_data, Mock())
        self.assertEqual(module.get_html(), sample_xml)

    def test_substitution_without_anonymous_student_id(self):
        sample_xml = '''%%USER_ID%%'''
        field_data = DictFieldData({'data': sample_xml})
        module_system = get_test_system()
        module_system.anonymous_student_id = None
        module = HtmlModule(self.descriptor, module_system, field_data, Mock())
        self.assertEqual(module.get_html(), sample_xml)


class HtmlDescriptorIndexingTestCase(unittest.TestCase):
    """
    Make sure that HtmlDescriptor can format data for indexing as expected.
    """
    shard = 1

    def test_index_dictionary_simple_html_module(self):
        sample_xml = '''
            <html>
                <p>Hello World!</p>
            </html>
        '''
        descriptor = instantiate_descriptor(data=sample_xml)
        self.assertEqual(descriptor.index_dictionary(), {
            "content": {"html_content": " Hello World! ", "display_name": "Text"},
            "content_type": "Text"
        })

    def test_index_dictionary_cdata_html_module(self):
        sample_xml_cdata = '''
            <html>
                <p>This has CDATA in it.</p>
                <![CDATA[This is just a CDATA!]]>
            </html>
        '''
        descriptor = instantiate_descriptor(data=sample_xml_cdata)
        self.assertEqual(descriptor.index_dictionary(), {
            "content": {"html_content": " This has CDATA in it. ", "display_name": "Text"},
            "content_type": "Text"
        })

    def test_index_dictionary_multiple_spaces_html_module(self):
        sample_xml_tab_spaces = '''
            <html>
                <p>     Text has spaces :)  </p>
            </html>
        '''
        descriptor = instantiate_descriptor(data=sample_xml_tab_spaces)
        self.assertEqual(descriptor.index_dictionary(), {
            "content": {"html_content": " Text has spaces :) ", "display_name": "Text"},
            "content_type": "Text"
        })

    def test_index_dictionary_html_module_with_comment(self):
        sample_xml_comment = '''
            <html>
                <p>This has HTML comment in it.</p>
                <!-- Html Comment -->
            </html>
        '''
        descriptor = instantiate_descriptor(data=sample_xml_comment)
        self.assertEqual(descriptor.index_dictionary(), {
            "content": {"html_content": " This has HTML comment in it. ", "display_name": "Text"},
            "content_type": "Text"
        })

    def test_index_dictionary_html_module_with_both_comments_and_cdata(self):
        sample_xml_mix_comment_cdata = '''
            <html>
                <!-- Beginning of the html -->
                <p>This has HTML comment in it.<!-- Commenting Content --></p>
                <!-- Here comes CDATA -->
                <![CDATA[This is just a CDATA!]]>
                <p>HTML end.</p>
            </html>
        '''
        descriptor = instantiate_descriptor(data=sample_xml_mix_comment_cdata)
        self.assertEqual(descriptor.index_dictionary(), {
            "content": {"html_content": " This has HTML comment in it. HTML end. ", "display_name": "Text"},
            "content_type": "Text"
        })

    def test_index_dictionary_html_module_with_script_and_style_tags(self):
        sample_xml_style_script_tags = '''
            <html>
                <style>p {color: green;}</style>
                <!-- Beginning of the html -->
                <p>This has HTML comment in it.<!-- Commenting Content --></p>
                <!-- Here comes CDATA -->
                <![CDATA[This is just a CDATA!]]>
                <p>HTML end.</p>
                <script>
                    var message = "Hello world!"
                </script>
            </html>
        '''
        descriptor = instantiate_descriptor(data=sample_xml_style_script_tags)
        self.assertEqual(descriptor.index_dictionary(), {
            "content": {"html_content": " This has HTML comment in it. HTML end. ", "display_name": "Text"},
            "content_type": "Text"
        })


class CourseInfoModuleTestCase(unittest.TestCase):
    """
    Make sure that CourseInfoModule renders updates properly.
    """
    shard = 1

    def test_updates_render(self):
        """
        Tests that a course info module will render its updates, even if they are malformed.
        """
        sample_update_data = [
            {
                "id": i,
                "date": data,
                "content": "This is a very important update!",
                "status": CourseInfoModule.STATUS_VISIBLE,
            } for i, data in enumerate(
                [
                    'January 1, 1970',
                    'Marchtober 45, -1963',
                    'Welcome!',
                    'Date means "title", right?'
                ]
            )
        ]
        info_module = CourseInfoModule(
            Mock(),
            get_test_system(),
            DictFieldData({'items': sample_update_data, 'data': ""}),
            Mock()
        )

        # Prior to TNL-4115, an exception would be raised when trying to parse invalid dates in this method
        try:
            info_module.get_html()
        except ValueError:
            self.fail("CourseInfoModule could not parse an invalid date!")

    def test_updates_order(self):
        """
        Tests that a course info module will render its updates in the correct order.
        """
        sample_update_data = [
            {
                "id": 3,
                "date": "March 18, 1982",
                "content": "This is a very important update that was inserted last with an older date!",
                "status": CourseInfoModule.STATUS_VISIBLE,
            },
            {
                "id": 1,
                "date": "January 1, 2012",
                "content": "This is a very important update that was inserted first!",
                "status": CourseInfoModule.STATUS_VISIBLE,
            },
            {
                "id": 2,
                "date": "January 1, 2012",
                "content": "This is a very important update that was inserted second!",
                "status": CourseInfoModule.STATUS_VISIBLE,
            }
        ]
        info_module = CourseInfoModule(
            Mock(),
            Mock(),
            DictFieldData({'items': sample_update_data, 'data': ""}),
            Mock()
        )

        # This is the expected context that should be used by the render function
        expected_context = {
            'visible_updates': [
                {
                    "id": 2,
                    "date": "January 1, 2012",
                    "content": "This is a very important update that was inserted second!",
                    "status": CourseInfoModule.STATUS_VISIBLE,
                },
                {
                    "id": 1,
                    "date": "January 1, 2012",
                    "content": "This is a very important update that was inserted first!",
                    "status": CourseInfoModule.STATUS_VISIBLE,
                },
                {
                    "id": 3,
                    "date": "March 18, 1982",
                    "content": "This is a very important update that was inserted last with an older date!",
                    "status": CourseInfoModule.STATUS_VISIBLE,
                }
            ],
            'hidden_updates': [],
        }
        template_name = "{0}/course_updates.html".format(info_module.TEMPLATE_DIR)
        info_module.get_html()
        # Assertion to validate that render function is called with the expected context
        info_module.system.render_template.assert_called_once_with(
            template_name,
            expected_context
        )
