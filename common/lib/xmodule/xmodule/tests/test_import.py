# -*- coding: utf-8 -*-

from __future__ import print_function
import datetime
from tempfile import mkdtemp

import ddt

from django.test import TestCase

from fs.osfs import OSFS
from lxml import etree
from mock import Mock, patch

from pytz import UTC
from six import text_type

from xmodule.xml_module import is_pointer_tag
from opaque_keys.edx.locator import BlockUsageLocator, CourseLocator
from xmodule.modulestore import only_xmodules
from xmodule.modulestore.xml import ImportSystem, XMLModuleStore, LibraryXMLModuleStore
from xmodule.modulestore.inheritance import compute_inherited_metadata
from xmodule.x_module import XModuleMixin
from xmodule.fields import Date
from xmodule.tests import DATA_DIR
from xmodule.modulestore.inheritance import InheritanceMixin
from opaque_keys.edx.keys import CourseKey

from xblock.core import XBlock
from xblock.fields import Scope, String, Integer
from xblock.runtime import KvsFieldData, DictKeyValueStore


ORG = 'test_org'
COURSE = 'test_course'
RUN = 'test_run'


class DummySystem(ImportSystem):

    @patch('xmodule.modulestore.xml.OSFS', lambda dir: OSFS(mkdtemp()))
    def __init__(self, load_error_modules, library=False):

        if library:
            xmlstore = LibraryXMLModuleStore("data_dir", source_dirs=[], load_error_modules=load_error_modules)
        else:
            xmlstore = XMLModuleStore("data_dir", source_dirs=[], load_error_modules=load_error_modules)
        course_id = CourseKey.from_string('/'.join([ORG, COURSE, RUN]))
        course_dir = "test_dir"
        error_tracker = Mock()

        super(DummySystem, self).__init__(
            xmlstore=xmlstore,
            course_id=course_id,
            course_dir=course_dir,
            error_tracker=error_tracker,
            load_error_modules=load_error_modules,
            mixins=(InheritanceMixin, XModuleMixin),
            field_data=KvsFieldData(DictKeyValueStore()),
        )

    def render_template(self, _template, _context):
        raise Exception("Shouldn't be called")


class BaseCourseTestCase(TestCase):
    '''Make sure module imports work properly, including for malformed inputs'''
    shard = 1

    @staticmethod
    def get_system(load_error_modules=True, library=False):
        '''Get a dummy system'''
        return DummySystem(load_error_modules, library=library)

    def get_course(self, name):
        """Get a test course by directory name.  If there's more than one, error."""
        print("Importing {0}".format(name))

        modulestore = XMLModuleStore(
            DATA_DIR,
            source_dirs=[name],
            xblock_mixins=(InheritanceMixin,),
            xblock_select=only_xmodules,
        )
        courses = modulestore.get_courses()
        self.assertEquals(len(courses), 1)
        return courses[0]


class GenericXBlock(XBlock):
    """XBlock for testing pure xblock xml import"""
    has_children = True
    field1 = String(default="something", scope=Scope.user_state)
    field2 = Integer(scope=Scope.user_state)


@ddt.ddt
class PureXBlockImportTest(BaseCourseTestCase):
    """
    Tests of import pure XBlocks (not XModules) from xml
    """
    shard = 1

    def assert_xblocks_are_good(self, block):
        """Assert a number of conditions that must be true for `block` to be good."""
        scope_ids = block.scope_ids
        self.assertIsNotNone(scope_ids.usage_id)
        self.assertIsNotNone(scope_ids.def_id)

        for child_id in block.children:
            child = block.runtime.get_block(child_id)
            self.assert_xblocks_are_good(child)

    @XBlock.register_temp_plugin(GenericXBlock)
    @ddt.data(
        "<genericxblock/>",
        "<genericxblock field1='abc' field2='23' />",
        "<genericxblock field1='abc' field2='23'><genericxblock/></genericxblock>",
    )
    @patch('xmodule.x_module.XModuleMixin.location')
    def test_parsing_pure_xblock(self, xml, mock_location):
        system = self.get_system(load_error_modules=False)
        descriptor = system.process_xml(xml)
        self.assertIsInstance(descriptor, GenericXBlock)
        self.assert_xblocks_are_good(descriptor)
        self.assertFalse(mock_location.called)


class ImportTestCase(BaseCourseTestCase):
    shard = 1
    date = Date()

    def test_fallback(self):
        '''Check that malformed xml loads as an ErrorDescriptor.'''

        # Use an exotic character to also flush out Unicode issues.
        bad_xml = u'''<sequential display_name="oops\N{SNOWMAN}"><video url="hi"></sequential>'''
        system = self.get_system()

        descriptor = system.process_xml(bad_xml)

        self.assertEqual(descriptor.__class__.__name__, 'ErrorDescriptorWithMixins')

    def test_unique_url_names(self):
        '''Check that each error gets its very own url_name'''
        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        bad_xml2 = '''<sequential url_name="oops"><video url="hi"></sequential>'''
        system = self.get_system()

        descriptor1 = system.process_xml(bad_xml)
        descriptor2 = system.process_xml(bad_xml2)

        self.assertNotEqual(descriptor1.location, descriptor2.location)

        # Check that each vertical gets its very own url_name
        bad_xml = '''<vertical display_name="abc"><problem url_name="exam1:2013_Spring:abc"/></vertical>'''
        bad_xml2 = '''<vertical display_name="abc"><problem url_name="exam2:2013_Spring:abc"/></vertical>'''

        descriptor1 = system.process_xml(bad_xml)
        descriptor2 = system.process_xml(bad_xml2)

        self.assertNotEqual(descriptor1.location, descriptor2.location)

    def test_reimport(self):
        '''Make sure an already-exported error xml tag loads properly'''

        self.maxDiff = None
        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        system = self.get_system()
        descriptor = system.process_xml(bad_xml)

        node = etree.Element('unknown')
        descriptor.add_xml_to_node(node)
        re_import_descriptor = system.process_xml(etree.tostring(node))

        self.assertEqual(re_import_descriptor.__class__.__name__, 'ErrorDescriptorWithMixins')

        self.assertEqual(descriptor.contents, re_import_descriptor.contents)
        self.assertEqual(descriptor.error_msg, re_import_descriptor.error_msg)

    def test_fixed_xml_tag(self):
        """Make sure a tag that's been fixed exports as the original tag type"""

        # create a error tag with valid xml contents
        root = etree.Element('error')
        good_xml = '''<sequential display_name="fixed"><video url="hi"/></sequential>'''
        root.text = good_xml

        xml_str_in = etree.tostring(root)

        # load it
        system = self.get_system()
        descriptor = system.process_xml(xml_str_in)

        # export it
        node = etree.Element('unknown')
        descriptor.add_xml_to_node(node)

        # Now make sure the exported xml is a sequential
        self.assertEqual(node.tag, 'sequential')

    def course_descriptor_inheritance_check(self, descriptor, from_date_string, unicorn_color, course_run=RUN):
        """
        Checks to make sure that metadata inheritance on a course descriptor is respected.
        """
        # pylint: disable=protected-access
        print((descriptor, descriptor._field_data))
        self.assertEqual(descriptor.due, ImportTestCase.date.from_json(from_date_string))

        # Check that the child inherits due correctly
        child = descriptor.get_children()[0]
        self.assertEqual(child.due, ImportTestCase.date.from_json(from_date_string))
        # need to convert v to canonical json b4 comparing
        self.assertEqual(
            ImportTestCase.date.to_json(ImportTestCase.date.from_json(from_date_string)),
            child.xblock_kvs.inherited_settings['due']
        )

        # Now export and check things
        file_system = OSFS(mkdtemp())
        descriptor.runtime.export_fs = file_system.makedir(u'course', recreate=True)
        node = etree.Element('unknown')
        descriptor.add_xml_to_node(node)

        # Check that the exported xml is just a pointer
        print(("Exported xml:", etree.tostring(node)))
        self.assertTrue(is_pointer_tag(node))
        # but it's a special case course pointer
        self.assertEqual(node.attrib['course'], COURSE)
        self.assertEqual(node.attrib['org'], ORG)

        # Does the course still have unicorns?
        with descriptor.runtime.export_fs.open(u'course/{course_run}.xml'.format(course_run=course_run)) as f:
            course_xml = etree.fromstring(f.read())

        self.assertEqual(course_xml.attrib['unicorn'], unicorn_color)

        # the course and org tags should be _only_ in the pointer
        self.assertNotIn('course', course_xml.attrib)
        self.assertNotIn('org', course_xml.attrib)

        # did we successfully strip the url_name from the definition contents?
        self.assertNotIn('url_name', course_xml.attrib)

        # Does the chapter tag now have a due attribute?
        # hardcoded path to child
        with descriptor.runtime.export_fs.open(u'chapter/ch.xml') as f:
            chapter_xml = etree.fromstring(f.read())
        self.assertEqual(chapter_xml.tag, 'chapter')
        self.assertNotIn('due', chapter_xml.attrib)

    def test_metadata_import_export(self):
        """Two checks:
            - unknown metadata is preserved across import-export
            - inherited metadata doesn't leak to children.
        """
        system = self.get_system()
        from_date_string = 'March 20 17:00'
        url_name = 'test1'
        unicorn_color = 'purple'
        start_xml = '''
        <course org="{org}" course="{course}"
                due="{due}" url_name="{url_name}" unicorn="{unicorn_color}">
            <chapter url="hi" url_name="ch" display_name="CH">
                <html url_name="h" display_name="H">Two houses, ...</html>
            </chapter>
        </course>'''.format(
            due=from_date_string, org=ORG, course=COURSE, url_name=url_name, unicorn_color=unicorn_color
        )
        descriptor = system.process_xml(start_xml)
        compute_inherited_metadata(descriptor)
        self.course_descriptor_inheritance_check(descriptor, from_date_string, unicorn_color)

    def test_library_metadata_import_export(self):
        """Two checks:
            - unknown metadata is preserved across import-export
            - inherited metadata doesn't leak to children.
        """
        system = self.get_system(library=True)
        from_date_string = 'March 26 17:00'
        url_name = 'test2'
        unicorn_color = 'rainbow'
        start_xml = '''
        <library org="TestOrg" library="TestLib" display_name="stuff">
            <course org="{org}" course="{course}"
                due="{due}" url_name="{url_name}" unicorn="{unicorn_color}">
                <chapter url="hi" url_name="ch" display_name="CH">
                    <html url_name="h" display_name="H">Two houses, ...</html>
                </chapter>
            </course>
        </library>'''.format(
            due=from_date_string, org=ORG, course=COURSE, url_name=url_name, unicorn_color=unicorn_color
        )
        descriptor = system.process_xml(start_xml)

        # pylint: disable=protected-access
        original_unwrapped = descriptor._unwrapped_field_data
        LibraryXMLModuleStore.patch_descriptor_kvs(descriptor)
        # '_unwrapped_field_data' is reset in `patch_descriptor_kvs`
        # pylint: disable=protected-access
        self.assertIsNot(original_unwrapped, descriptor._unwrapped_field_data)
        compute_inherited_metadata(descriptor)
        # Check the course module, since it has inheritance
        descriptor = descriptor.get_children()[0]
        self.course_descriptor_inheritance_check(descriptor, from_date_string, unicorn_color)

    def test_metadata_no_inheritance(self):
        """
        Checks that default value of None (for due) does not get marked as inherited when a
        course is the root block.
        """
        system = self.get_system()
        url_name = 'test1'
        start_xml = '''
        <course org="{org}" course="{course}"
                url_name="{url_name}" unicorn="purple">
            <chapter url="hi" url_name="ch" display_name="CH">
                <html url_name="h" display_name="H">Two houses, ...</html>
            </chapter>
        </course>'''.format(org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        compute_inherited_metadata(descriptor)
        self.course_descriptor_no_inheritance_check(descriptor)

    def test_library_metadata_no_inheritance(self):
        """
        Checks that the default value of None (for due) does not get marked as inherited when a
        library is the root block.
        """
        system = self.get_system()
        url_name = 'test1'
        start_xml = '''
        <library org="TestOrg" library="TestLib" display_name="stuff">
            <course org="{org}" course="{course}"
                    url_name="{url_name}" unicorn="purple">
                <chapter url="hi" url_name="ch" display_name="CH">
                    <html url_name="h" display_name="H">Two houses, ...</html>
                </chapter>
            </course>
        </library>'''.format(org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        LibraryXMLModuleStore.patch_descriptor_kvs(descriptor)
        compute_inherited_metadata(descriptor)
        # Run the checks on the course node instead.
        descriptor = descriptor.get_children()[0]
        self.course_descriptor_no_inheritance_check(descriptor)

    def course_descriptor_no_inheritance_check(self, descriptor):
        """
        Verifies that a default value of None (for due) does not get marked as inherited.
        """
        self.assertEqual(descriptor.due, None)

        # Check that the child does not inherit a value for due
        child = descriptor.get_children()[0]
        self.assertEqual(child.due, None)

        # Check that the child hasn't started yet
        self.assertLessEqual(
            datetime.datetime.now(UTC),
            child.start
        )

    def override_metadata_check(self, descriptor, child, course_due, child_due):
        """
        Verifies that due date can be overriden at child level.
        """
        self.assertEqual(descriptor.due, ImportTestCase.date.from_json(course_due))
        self.assertEqual(child.due, ImportTestCase.date.from_json(child_due))
        # Test inherited metadata. Due does not appear here (because explicitly set on child).
        self.assertEqual(
            ImportTestCase.date.to_json(ImportTestCase.date.from_json(course_due)),
            child.xblock_kvs.inherited_settings['due']
        )

    def test_metadata_override_default(self):
        """
        Checks that due date can be overriden at child level when a course is the root.
        """
        system = self.get_system()
        course_due = 'March 20 17:00'
        child_due = 'April 10 00:00'
        url_name = 'test1'
        start_xml = '''
        <course org="{org}" course="{course}"
                due="{due}" url_name="{url_name}" unicorn="purple">
            <chapter url="hi" url_name="ch" display_name="CH">
                <html url_name="h" display_name="H">Two houses, ...</html>
            </chapter>
        </course>'''.format(due=course_due, org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        child = descriptor.get_children()[0]
        # pylint: disable=protected-access
        child._field_data.set(child, 'due', child_due)
        compute_inherited_metadata(descriptor)
        self.override_metadata_check(descriptor, child, course_due, child_due)

    def test_library_metadata_override_default(self):
        """
        Checks that due date can be overriden at child level when a library is the root.
        """
        system = self.get_system()
        course_due = 'March 20 17:00'
        child_due = 'April 10 00:00'
        url_name = 'test1'
        start_xml = '''
        <library org="TestOrg" library="TestLib" display_name="stuff">
            <course org="{org}" course="{course}"
                    due="{due}" url_name="{url_name}" unicorn="purple">
                <chapter url="hi" url_name="ch" display_name="CH">
                    <html url_name="h" display_name="H">Two houses, ...</html>
                </chapter>
            </course>
        </library>'''.format(due=course_due, org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        LibraryXMLModuleStore.patch_descriptor_kvs(descriptor)
        # Chapter is two levels down here.
        child = descriptor.get_children()[0].get_children()[0]
        # pylint: disable=protected-access
        child._field_data.set(child, 'due', child_due)
        compute_inherited_metadata(descriptor)
        descriptor = descriptor.get_children()[0]
        self.override_metadata_check(descriptor, child, course_due, child_due)

    def test_is_pointer_tag(self):
        """
        Check that is_pointer_tag works properly.
        """

        yes = ["""<html url_name="blah"/>""",
               """<html url_name="blah"></html>""",
               """<html url_name="blah">    </html>""",
               """<problem url_name="blah"/>""",
               """<course org="HogwartsX" course="Mathemagics" url_name="3.14159"/>"""]

        no = ["""<html url_name="blah" also="this"/>""",
              """<html url_name="blah">some text</html>""",
              """<problem url_name="blah"><sub>tree</sub></problem>""",
              """<course org="HogwartsX" course="Mathemagics" url_name="3.14159">
                     <chapter>3</chapter>
                  </course>
              """]

        for xml_str in yes:
            print("should be True for {0}".format(xml_str))
            self.assertTrue(is_pointer_tag(etree.fromstring(xml_str)))

        for xml_str in no:
            print("should be False for {0}".format(xml_str))
            self.assertFalse(is_pointer_tag(etree.fromstring(xml_str)))

    def test_metadata_inherit(self):
        """Make sure that metadata is inherited properly"""

        print("Starting import")
        course = self.get_course('toy')

        def check_for_key(key, node, value):
            "recursive check for presence of key"
            print("Checking {0}".format(text_type(node.location)))
            self.assertEqual(getattr(node, key), value)
            for c in node.get_children():
                check_for_key(key, c, value)

        check_for_key('graceperiod', course, course.graceperiod)

    def test_policy_loading(self):
        """Make sure that when two courses share content with the same
        org and course names, policy applies to the right one."""

        toy = self.get_course('toy')
        two_toys = self.get_course('two_toys')

        self.assertEqual(toy.url_name, "2012_Fall")
        self.assertEqual(two_toys.url_name, "TT_2012_Fall")

        toy_ch = toy.get_children()[0]
        two_toys_ch = two_toys.get_children()[0]

        self.assertEqual(toy_ch.display_name, "Overview")
        self.assertEqual(two_toys_ch.display_name, "Two Toy Overview")

        # Also check that the grading policy loaded
        self.assertEqual(two_toys.grade_cutoffs['C'], 0.5999)

        # Also check that keys from policy are run through the
        # appropriate attribute maps -- 'graded' should be True, not 'true'
        self.assertEqual(toy.graded, True)

    def test_static_tabs_import(self):
        """Make sure that the static tabs are imported correctly"""

        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['toy'])

        location_tab_syllabus = BlockUsageLocator(CourseLocator("edX", "toy", "2012_Fall", deprecated=True),
                                                  "static_tab", "syllabus", deprecated=True)
        toy_tab_syllabus = modulestore.get_item(location_tab_syllabus)
        self.assertEqual(toy_tab_syllabus.display_name, 'Syllabus')
        self.assertEqual(toy_tab_syllabus.course_staff_only, False)

        location_tab_resources = BlockUsageLocator(CourseLocator("edX", "toy", "2012_Fall", deprecated=True),
                                                   "static_tab", "resources", deprecated=True)
        toy_tab_resources = modulestore.get_item(location_tab_resources)
        self.assertEqual(toy_tab_resources.display_name, 'Resources')
        self.assertEqual(toy_tab_resources.course_staff_only, True)

    def test_definition_loading(self):
        """When two courses share the same org and course name and
        both have a module with the same url_name, the definitions shouldn't clash.

        TODO (vshnayder): once we have a CMS, this shouldn't
        happen--locations should uniquely name definitions.  But in
        our imperfect XML world, it can (and likely will) happen."""

        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['toy', 'two_toys'])

        location = BlockUsageLocator(CourseLocator("edX", "toy", "2012_Fall", deprecated=True),
                                     "video", "Welcome", deprecated=True)
        toy_video = modulestore.get_item(location)
        location_two = BlockUsageLocator(CourseLocator("edX", "toy", "TT_2012_Fall", deprecated=True),
                                         "video", "Welcome", deprecated=True)
        two_toy_video = modulestore.get_item(location_two)
        self.assertEqual(toy_video.youtube_id_1_0, "p2Q6BrNhdh8")
        self.assertEqual(two_toy_video.youtube_id_1_0, "p2Q6BrNhdh9")

    def test_colon_in_url_name(self):
        """Ensure that colons in url_names convert to file paths properly"""

        print("Starting import")
        # Not using get_courses because we need the modulestore object too afterward
        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['toy'])
        courses = modulestore.get_courses()
        self.assertEquals(len(courses), 1)
        course = courses[0]

        print("course errors:")
        for (msg, err) in modulestore.get_course_errors(course.id):
            print(msg)
            print(err)

        chapters = course.get_children()
        self.assertEquals(len(chapters), 5)

        ch2 = chapters[1]
        self.assertEquals(ch2.url_name, "secret:magic")

        print("Ch2 location: ", ch2.location)

        also_ch2 = modulestore.get_item(ch2.location)
        self.assertEquals(ch2, also_ch2)

        print("making sure html loaded")
        loc = course.id.make_usage_key('html', 'secret:toylab')
        html = modulestore.get_item(loc)
        self.assertEquals(html.display_name, "Toy lab")

    def test_unicode(self):
        """Check that courses with unicode characters in filenames and in
        org/course/name import properly. Currently, this means: (a) Having
        files with unicode names does not prevent import; (b) if files are not
        loaded because of unicode filenames, there are appropriate
        exceptions/errors to that effect."""

        print("Starting import")
        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['test_unicode'])
        courses = modulestore.get_courses()
        self.assertEquals(len(courses), 1)
        course = courses[0]

        print("course errors:")

        # Expect to find an error/exception about characters in "®esources"
        expect = "InvalidKeyError"
        errors = [
            (msg.encode("utf-8"), err.encode("utf-8"))
            for msg, err
            in modulestore.get_course_errors(course.id)
        ]

        self.assertTrue(any(
            expect in msg or expect in err
            for msg, err in errors
        ))
        chapters = course.get_children()
        self.assertEqual(len(chapters), 4)

    def test_url_name_mangling(self):
        """
        Make sure that url_names are only mangled once.
        """

        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['toy'])

        toy_id = CourseKey.from_string('edX/toy/2012_Fall')

        course = modulestore.get_course(toy_id)
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 4)

        for i in (2, 3):
            video = sections[i]
            # Name should be 'video_{hash}'
            print("video {0} url_name: {1}".format(i, video.url_name))
            self.assertEqual(len(video.url_name), len('video_') + 12)

    def test_poll_and_conditional_import(self):
        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['conditional_and_poll'])

        course = modulestore.get_courses()[0]
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 1)

        conditional_location = course.id.make_usage_key('conditional', 'condone')
        module = modulestore.get_item(conditional_location)
        self.assertEqual(len(module.children), 1)

        poll_location = course.id.make_usage_key('poll_question', 'first_poll')
        module = modulestore.get_item(poll_location)
        self.assertEqual(len(module.get_children()), 0)
        self.assertEqual(module.voted, False)
        self.assertEqual(module.poll_answer, '')
        self.assertEqual(module.poll_answers, {})
        self.assertEqual(
            module.answers,
            [
                {'text': u'Yes', 'id': 'Yes'},
                {'text': u'No', 'id': 'No'},
                {'text': u"Don't know", 'id': 'Dont_know'}
            ]
        )

    def test_error_on_import(self):
        '''Check that when load_error_module is false, an exception is raised, rather than returning an ErrorModule'''

        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        system = self.get_system(False)

        self.assertRaises(etree.XMLSyntaxError, system.process_xml, bad_xml)

    def test_word_cloud_import(self):
        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['word_cloud'])

        course = modulestore.get_courses()[0]
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 1)

        location = course.id.make_usage_key('word_cloud', 'cloud1')
        module = modulestore.get_item(location)
        self.assertEqual(len(module.get_children()), 0)
        self.assertEqual(module.num_inputs, 5)
        self.assertEqual(module.num_top_words, 250)

    def test_cohort_config(self):
        """
        Check that cohort config parsing works right.

        Note: The cohort config on the CourseModule is no longer used.
        See openedx.core.djangoapps.course_groups.models.CourseCohortSettings.
        """
        modulestore = XMLModuleStore(DATA_DIR, source_dirs=['toy'])

        toy_id = CourseKey.from_string('edX/toy/2012_Fall')

        course = modulestore.get_course(toy_id)

        # No config -> False
        self.assertFalse(course.is_cohorted)

        # empty config -> False
        course.cohort_config = {}
        self.assertFalse(course.is_cohorted)

        # false config -> False
        course.cohort_config = {'cohorted': False}
        self.assertFalse(course.is_cohorted)

        # and finally...
        course.cohort_config = {'cohorted': True}
        self.assertTrue(course.is_cohorted)
