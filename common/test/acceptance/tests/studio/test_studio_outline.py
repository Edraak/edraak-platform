# -*- coding: utf-8 -*-
"""
Acceptance tests for studio related to the outline page.
"""
import itertools
import json
from datetime import datetime, timedelta
from pytz import UTC
from unittest import skip

from base_studio_test import StudioCourseTest
from common.test.acceptance.fixtures.config import ConfigModelFixture
from common.test.acceptance.fixtures.course import XBlockFixtureDesc
from common.test.acceptance.pages.lms.course_home import CourseHomePage
from common.test.acceptance.pages.lms.courseware import CoursewarePage
from common.test.acceptance.pages.lms.progress import ProgressPage
from common.test.acceptance.pages.studio.overview import ContainerPage, CourseOutlinePage, ExpandCollapseLinkState
from common.test.acceptance.pages.studio.settings import SettingsPage
from common.test.acceptance.pages.studio.checklists import CourseChecklistsPage
from common.test.acceptance.pages.studio.settings_advanced import AdvancedSettingsPage
from common.test.acceptance.pages.studio.settings_group_configurations import GroupConfigurationsPage
from common.test.acceptance.pages.studio.utils import add_discussion, drag, verify_ordering
from common.test.acceptance.tests.helpers import disable_animations, load_data_str
from openedx.core.lib.tests import attr

SECTION_NAME = 'Test Section'
SUBSECTION_NAME = 'Test Subsection'
UNIT_NAME = 'Test Unit'


class CourseOutlineTest(StudioCourseTest):
    """
    Base class for all course outline tests
    """

    def setUp(self):
        """
        Install a course with no content using a fixture.
        """
        super(CourseOutlineTest, self).setUp()
        self.course_outline_page = CourseOutlinePage(
            self.browser, self.course_info['org'], self.course_info['number'], self.course_info['run']
        )
        self.advanced_settings = AdvancedSettingsPage(
            self.browser, self.course_info['org'], self.course_info['number'], self.course_info['run']
        )

    def populate_course_fixture(self, course_fixture):
        """ Install a course with sections/problems, tabs, updates, and handouts """
        course_fixture.add_children(
            XBlockFixtureDesc('chapter', SECTION_NAME).add_children(
                XBlockFixtureDesc('sequential', SUBSECTION_NAME).add_children(
                    XBlockFixtureDesc('vertical', UNIT_NAME).add_children(
                        XBlockFixtureDesc('problem', 'Test Problem 1', data=load_data_str('multiple_choice.xml')),
                        XBlockFixtureDesc('html', 'Test HTML Component'),
                        XBlockFixtureDesc('discussion', 'Test Discussion Component')
                    )
                )
            )
        )

    def do_action_and_verify(self, outline_page, action, expected_ordering):
        """
        Perform the supplied action and then verify the resulting ordering.
        """
        if outline_page is None:
            outline_page = self.course_outline_page.visit()

        action(outline_page)
        verify_ordering(self, outline_page, expected_ordering)

        # Reload the page and expand all subsections to see that the change was persisted.
        outline_page = self.course_outline_page.visit()
        outline_page.q(css='.outline-item.outline-subsection.is-collapsed .ui-toggle-expansion').click()
        verify_ordering(self, outline_page, expected_ordering)


@attr(shard=3)
class CourseOutlineDragAndDropTest(CourseOutlineTest):
    """
    Tests of drag and drop within the outline page.
    """
    __test__ = True

    def populate_course_fixture(self, course_fixture):
        """
        Create a course with one section, two subsections, and four units
        """
        # with collapsed outline
        self.chap_1_handle = 0
        self.chap_1_seq_1_handle = 1

        # with first sequential expanded
        self.seq_1_vert_1_handle = 2
        self.seq_1_vert_2_handle = 3
        self.chap_1_seq_2_handle = 4

        course_fixture.add_children(
            XBlockFixtureDesc('chapter', "1").add_children(
                XBlockFixtureDesc('sequential', '1.1').add_children(
                    XBlockFixtureDesc('vertical', '1.1.1'),
                    XBlockFixtureDesc('vertical', '1.1.2')
                ),
                XBlockFixtureDesc('sequential', '1.2').add_children(
                    XBlockFixtureDesc('vertical', '1.2.1'),
                    XBlockFixtureDesc('vertical', '1.2.2')
                )
            )
        )

    def drag_and_verify(self, source, target, expected_ordering, outline_page=None):
        self.do_action_and_verify(
            outline_page,
            lambda (outline): drag(outline, source, target),
            expected_ordering
        )

    @skip("Fails in Firefox 45 but passes in Chrome")
    def test_drop_unit_in_collapsed_subsection(self):
        """
        Drag vertical "1.1.2" from subsection "1.1" into collapsed subsection "1.2" which already
        have its own verticals.
        """
        course_outline_page = self.course_outline_page.visit()
        # expand first subsection
        course_outline_page.q(css='.outline-item.outline-subsection.is-collapsed .ui-toggle-expansion').first.click()

        expected_ordering = [{"1": ["1.1", "1.2"]},
                             {"1.1": ["1.1.1"]},
                             {"1.2": ["1.1.2", "1.2.1", "1.2.2"]}]
        self.drag_and_verify(self.seq_1_vert_2_handle, self.chap_1_seq_2_handle, expected_ordering, course_outline_page)


@attr(shard=3)
class WarningMessagesTest(CourseOutlineTest):
    """
    Feature: Warning messages on sections, subsections, and units
    """

    __test__ = True

    STAFF_ONLY_WARNING = 'Contains staff only content'
    LIVE_UNPUBLISHED_WARNING = 'Unpublished changes to live content'
    FUTURE_UNPUBLISHED_WARNING = 'Unpublished changes to content that will release in the future'
    NEVER_PUBLISHED_WARNING = 'Unpublished units will not be released'

    class PublishState(object):
        """
        Default values for representing the published state of a unit
        """
        NEVER_PUBLISHED = 1
        UNPUBLISHED_CHANGES = 2
        PUBLISHED = 3
        VALUES = [NEVER_PUBLISHED, UNPUBLISHED_CHANGES, PUBLISHED]

    class UnitState(object):
        """ Represents the state of a unit """

        def __init__(self, is_released, publish_state, is_locked):
            """ Creates a new UnitState with the given properties """
            self.is_released = is_released
            self.publish_state = publish_state
            self.is_locked = is_locked

        @property
        def name(self):
            """ Returns an appropriate name based on the properties of the unit """
            result = "Released " if self.is_released else "Unreleased "
            if self.publish_state == WarningMessagesTest.PublishState.NEVER_PUBLISHED:
                result += "Never Published "
            elif self.publish_state == WarningMessagesTest.PublishState.UNPUBLISHED_CHANGES:
                result += "Unpublished Changes "
            else:
                result += "Published "
            result += "Locked" if self.is_locked else "Unlocked"
            return result

    def populate_course_fixture(self, course_fixture):
        """ Install a course with various configurations that could produce warning messages """

        # Define the dimensions that map to the UnitState constructor
        features = [
            [True, False],             # Possible values for is_released
            self.PublishState.VALUES,  # Possible values for publish_state
            [True, False]              # Possible values for is_locked
        ]

        # Add a fixture for every state in the product of features
        course_fixture.add_children(*[
            self._build_fixture(self.UnitState(*state)) for state in itertools.product(*features)
        ])

    def _build_fixture(self, unit_state):
        """ Returns an XBlockFixtureDesc with a section, subsection, and possibly unit that has the given state. """
        name = unit_state.name
        start = (datetime(1984, 3, 4) if unit_state.is_released else datetime.now(UTC) + timedelta(1)).isoformat()

        subsection = XBlockFixtureDesc('sequential', name, metadata={'start': start})

        # Children of never published subsections will be added on demand via _ensure_unit_present
        return XBlockFixtureDesc('chapter', name).add_children(
            subsection if unit_state.publish_state == self.PublishState.NEVER_PUBLISHED
            else subsection.add_children(
                XBlockFixtureDesc('vertical', name, metadata={
                    'visible_to_staff_only': True if unit_state.is_locked else None
                })
            )
        )

    def test_released_never_published_locked(self):
        """ Tests that released never published locked units display staff only warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=True, publish_state=self.PublishState.NEVER_PUBLISHED, is_locked=True),
            self.STAFF_ONLY_WARNING
        )

    def test_released_never_published_unlocked(self):
        """ Tests that released never published unlocked units display 'Unpublished units will not be released' """
        self._verify_unit_warning(
            self.UnitState(is_released=True, publish_state=self.PublishState.NEVER_PUBLISHED, is_locked=False),
            self.NEVER_PUBLISHED_WARNING
        )

    def test_released_unpublished_changes_locked(self):
        """ Tests that released unpublished changes locked units display staff only warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=True, publish_state=self.PublishState.UNPUBLISHED_CHANGES, is_locked=True),
            self.STAFF_ONLY_WARNING
        )

    def test_released_unpublished_changes_unlocked(self):
        """ Tests that released unpublished changes unlocked units display 'Unpublished changes to live content' """
        self._verify_unit_warning(
            self.UnitState(is_released=True, publish_state=self.PublishState.UNPUBLISHED_CHANGES, is_locked=False),
            self.LIVE_UNPUBLISHED_WARNING
        )

    def test_released_published_locked(self):
        """ Tests that released published locked units display staff only warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=True, publish_state=self.PublishState.PUBLISHED, is_locked=True),
            self.STAFF_ONLY_WARNING
        )

    def test_released_published_unlocked(self):
        """ Tests that released published unlocked units display no warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=True, publish_state=self.PublishState.PUBLISHED, is_locked=False),
            None
        )

    def test_unreleased_never_published_locked(self):
        """ Tests that unreleased never published locked units display staff only warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=False, publish_state=self.PublishState.NEVER_PUBLISHED, is_locked=True),
            self.STAFF_ONLY_WARNING
        )

    def test_unreleased_never_published_unlocked(self):
        """ Tests that unreleased never published unlocked units display 'Unpublished units will not be released' """
        self._verify_unit_warning(
            self.UnitState(is_released=False, publish_state=self.PublishState.NEVER_PUBLISHED, is_locked=False),
            self.NEVER_PUBLISHED_WARNING
        )

    def test_unreleased_unpublished_changes_locked(self):
        """ Tests that unreleased unpublished changes locked units display staff only warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=False, publish_state=self.PublishState.UNPUBLISHED_CHANGES, is_locked=True),
            self.STAFF_ONLY_WARNING
        )

    def test_unreleased_unpublished_changes_unlocked(self):
        """
        Tests that unreleased unpublished changes unlocked units display 'Unpublished changes to content that will
        release in the future'
        """
        self._verify_unit_warning(
            self.UnitState(is_released=False, publish_state=self.PublishState.UNPUBLISHED_CHANGES, is_locked=False),
            self.FUTURE_UNPUBLISHED_WARNING
        )

    def test_unreleased_published_locked(self):
        """ Tests that unreleased published locked units display staff only warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=False, publish_state=self.PublishState.PUBLISHED, is_locked=True),
            self.STAFF_ONLY_WARNING
        )

    def test_unreleased_published_unlocked(self):
        """ Tests that unreleased published unlocked units display no warnings """
        self._verify_unit_warning(
            self.UnitState(is_released=False, publish_state=self.PublishState.PUBLISHED, is_locked=False),
            None
        )

    def _verify_unit_warning(self, unit_state, expected_status_message):
        """
        Verifies that the given unit's messages match the expected messages.
        If expected_status_message is None, then the unit status message is expected to not be present.
        """
        self._ensure_unit_present(unit_state)
        self.course_outline_page.visit()
        section = self.course_outline_page.section(unit_state.name)
        subsection = section.subsection_at(0)
        subsection.expand_subsection()
        unit = subsection.unit_at(0)
        if expected_status_message == self.STAFF_ONLY_WARNING:
            self.assertEqual(section.status_message, self.STAFF_ONLY_WARNING)
            self.assertEqual(subsection.status_message, self.STAFF_ONLY_WARNING)
            self.assertEqual(unit.status_message, self.STAFF_ONLY_WARNING)
        else:
            self.assertFalse(section.has_status_message)
            self.assertFalse(subsection.has_status_message)
            if expected_status_message:
                self.assertEqual(unit.status_message, expected_status_message)
            else:
                self.assertFalse(unit.has_status_message)

    def _ensure_unit_present(self, unit_state):
        """ Ensures that a unit with the given state is present on the course outline """
        if unit_state.publish_state == self.PublishState.PUBLISHED:
            return

        name = unit_state.name
        self.course_outline_page.visit()
        subsection = self.course_outline_page.section(name).subsection(name)
        subsection.expand_subsection()

        if unit_state.publish_state == self.PublishState.UNPUBLISHED_CHANGES:
            unit = subsection.unit(name).go_to()
            add_discussion(unit)
        elif unit_state.publish_state == self.PublishState.NEVER_PUBLISHED:
            subsection.add_unit()
            unit = ContainerPage(self.browser, None)
            unit.wait_for_page()

        if unit.is_staff_locked != unit_state.is_locked:
            unit.toggle_staff_lock()


@attr(shard=3)
class EditingSectionsTest(CourseOutlineTest):
    """
    Feature: Editing Release date, Due date and grading type.
    """

    __test__ = True

    def test_can_edit_subsection(self):
        """
        Scenario: I can edit settings of subsection.

            Given that I have created a subsection
            Then I see release date, due date and grading policy of subsection in course outline
            When I click on the configuration icon
            Then edit modal window is shown
            And release date, due date and grading policy fields present
            And they have correct initial values
            Then I set new values for these fields
            And I click save button on the modal
            Then I see release date, due date and grading policy of subsection in course outline
        """
        self.course_outline_page.visit()
        subsection = self.course_outline_page.section(SECTION_NAME).subsection(SUBSECTION_NAME)

        # Verify that Release date visible by default
        self.assertTrue(subsection.release_date)
        # Verify that Due date and Policy hidden by default
        self.assertFalse(subsection.due_date)
        self.assertFalse(subsection.policy)

        modal = subsection.edit()

        # Verify fields
        self.assertTrue(modal.has_release_date())
        self.assertTrue(modal.has_release_time())
        self.assertTrue(modal.has_due_date())
        self.assertTrue(modal.has_due_time())
        self.assertTrue(modal.has_policy())

        # Verify initial values
        self.assertEqual(modal.release_date, u'1/1/1970')
        self.assertEqual(modal.release_time, u'00:00')
        self.assertEqual(modal.due_date, u'')
        self.assertEqual(modal.due_time, u'')
        self.assertEqual(modal.policy, u'Not Graded')

        # Set new values
        modal.release_date = '3/12/1972'
        modal.release_time = '04:01'
        modal.due_date = '7/21/2014'
        modal.due_time = '23:39'
        modal.policy = 'Lab'

        modal.save()
        self.assertIn(u'Released: Mar 12, 1972', subsection.release_date)
        self.assertIn(u'04:01', subsection.release_date)
        self.assertIn(u'Due: Jul 21, 2014', subsection.due_date)
        self.assertIn(u'23:39', subsection.due_date)
        self.assertIn(u'Lab', subsection.policy)

    def test_can_edit_section(self):
        """
        Scenario: I can edit settings of section.

            Given that I have created a section
            Then I see release date of section in course outline
            When I click on the configuration icon
            Then edit modal window is shown
            And release date field present
            And it has correct initial value
            Then I set new value for this field
            And I click save button on the modal
            Then I see release date of section in course outline
        """
        self.course_outline_page.visit()
        section = self.course_outline_page.section(SECTION_NAME)

        # Verify that Release date visible by default
        self.assertTrue(section.release_date)
        # Verify that Due date and Policy are not present
        self.assertFalse(section.due_date)
        self.assertFalse(section.policy)

        modal = section.edit()
        # Verify fields
        self.assertTrue(modal.has_release_date())
        self.assertFalse(modal.has_due_date())
        self.assertFalse(modal.has_policy())

        # Verify initial value
        self.assertEqual(modal.release_date, u'1/1/1970')

        # Set new value
        modal.release_date = '5/14/1969'

        modal.save()
        self.assertIn(u'Released: May 14, 1969', section.release_date)
        # Verify that Due date and Policy are not present
        self.assertFalse(section.due_date)
        self.assertFalse(section.policy)

    def test_subsection_is_graded_in_lms(self):
        """
        Scenario: I can grade subsection from course outline page.

            Given I visit progress page
            And I see that problem in subsection has grading type "Practice"
            Then I visit course outline page
            And I click on the configuration icon of subsection
            And I set grading policy to "Lab"
            And I click save button on the modal
            Then I visit progress page
            And I see that problem in subsection has grading type "Problem"
        """
        progress_page = ProgressPage(self.browser, self.course_id)
        progress_page.visit()
        progress_page.wait_for_page()
        self.assertEqual(u'Practice', progress_page.grading_formats[0])
        self.course_outline_page.visit()

        subsection = self.course_outline_page.section(SECTION_NAME).subsection(SUBSECTION_NAME)
        modal = subsection.edit()
        # Set new values
        modal.policy = 'Lab'
        modal.save()

        progress_page.visit()

        self.assertEqual(u'Problem', progress_page.grading_formats[0])

    def test_unchanged_release_date_is_not_saved(self):
        """
        Scenario: Saving a subsection without changing the release date will not override the release date
            Given that I have created a section with a subsection
            When I open the settings modal for the subsection
            And I pressed save
            And I open the settings modal for the section
            And I change the release date to 07/20/1969
            And I press save
            Then the subsection and the section have the release date 07/20/1969
        """
        self.course_outline_page.visit()

        modal = self.course_outline_page.section_at(0).subsection_at(0).edit()
        modal.save()

        modal = self.course_outline_page.section_at(0).edit()
        modal.release_date = '7/20/1969'
        modal.save()

        release_text = 'Released: Jul 20, 1969'
        self.assertIn(release_text, self.course_outline_page.section_at(0).release_date)
        self.assertIn(release_text, self.course_outline_page.section_at(0).subsection_at(0).release_date)


@attr(shard=3)
class UnitAccessTest(CourseOutlineTest):
    """
    Feature: Units can be restricted and unrestricted to certain groups from the course outline.
    """

    __test__ = True

    def setUp(self):
        super(UnitAccessTest, self).setUp()
        self.group_configurations_page = GroupConfigurationsPage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )
        self.content_group_a = "Test Group A"
        self.content_group_b = "Test Group B"

        self.group_configurations_page.visit()
        self.group_configurations_page.create_first_content_group()
        config_a = self.group_configurations_page.content_groups[0]
        config_a.name = self.content_group_a
        config_a.save()
        self.content_group_a_id = config_a.id

        self.group_configurations_page.add_content_group()
        config_b = self.group_configurations_page.content_groups[1]
        config_b.name = self.content_group_b
        config_b.save()
        self.content_group_b_id = config_b.id

    def populate_course_fixture(self, course_fixture):
        """
        Create a course with one section, one subsection, and two units
        """
        # with collapsed outline
        self.chap_1_handle = 0
        self.chap_1_seq_1_handle = 1

        # with first sequential expanded
        self.seq_1_vert_1_handle = 2
        self.seq_1_vert_2_handle = 3
        self.chap_1_seq_2_handle = 4

        course_fixture.add_children(
            XBlockFixtureDesc('chapter', "1").add_children(
                XBlockFixtureDesc('sequential', '1.1').add_children(
                    XBlockFixtureDesc('vertical', '1.1.1'),
                    XBlockFixtureDesc('vertical', '1.1.2')
                )
            )
        )


@attr(shard=14)
class StaffLockTest(CourseOutlineTest):
    """
    Feature: Sections, subsections, and units can be locked and unlocked from the course outline.
    """

    __test__ = True

    def populate_course_fixture(self, course_fixture):
        """ Create a course with one section, two subsections, and four units """
        course_fixture.add_children(
            XBlockFixtureDesc('chapter', '1').add_children(
                XBlockFixtureDesc('sequential', '1.1').add_children(
                    XBlockFixtureDesc('vertical', '1.1.1'),
                    XBlockFixtureDesc('vertical', '1.1.2')
                ),
                XBlockFixtureDesc('sequential', '1.2').add_children(
                    XBlockFixtureDesc('vertical', '1.2.1'),
                    XBlockFixtureDesc('vertical', '1.2.2')
                )
            )
        )

    def _verify_descendants_are_staff_only(self, item):
        """Verifies that all the descendants of item are staff only"""
        self.assertTrue(item.is_staff_only)
        if hasattr(item, 'children'):
            for child in item.children():
                self._verify_descendants_are_staff_only(child)

    def _remove_staff_lock_and_verify_warning(self, outline_item, expect_warning):
        """Removes staff lock from a course outline item and checks whether or not a warning appears."""
        modal = outline_item.edit()
        modal.is_explicitly_locked = False
        if expect_warning:
            self.assertTrue(modal.shows_staff_lock_warning())
        else:
            self.assertFalse(modal.shows_staff_lock_warning())
        modal.save()

    def _toggle_lock_on_unlocked_item(self, outline_item):
        """Toggles outline_item's staff lock on and then off, verifying the staff lock warning"""
        self.assertFalse(outline_item.has_staff_lock_warning)
        outline_item.set_staff_lock(True)
        self.assertTrue(outline_item.has_staff_lock_warning)
        self._verify_descendants_are_staff_only(outline_item)
        outline_item.set_staff_lock(False)
        self.assertFalse(outline_item.has_staff_lock_warning)

    def _verify_explicit_staff_lock_remains_after_unlocking_parent(self, child_item, parent_item):
        """Verifies that child_item's explicit staff lock remains after removing parent_item's staff lock"""
        child_item.set_staff_lock(True)
        parent_item.set_staff_lock(True)
        self.assertTrue(parent_item.has_staff_lock_warning)
        self.assertTrue(child_item.has_staff_lock_warning)
        parent_item.set_staff_lock(False)
        self.assertFalse(parent_item.has_staff_lock_warning)
        self.assertTrue(child_item.has_staff_lock_warning)

    def test_units_can_be_locked(self):
        """
        Scenario: Units can be locked and unlocked from the course outline page
            Given I have a course with a unit
            When I click on the configuration icon
            And I enable explicit staff locking
            And I click save
            Then the unit shows a staff lock warning
            And when I click on the configuration icon
            And I disable explicit staff locking
            And I click save
            Then the unit does not show a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        unit = self.course_outline_page.section_at(0).subsection_at(0).unit_at(0)
        self._toggle_lock_on_unlocked_item(unit)

    def test_subsections_can_be_locked(self):
        """
        Scenario: Subsections can be locked and unlocked from the course outline page
            Given I have a course with a subsection
            When I click on the subsection's configuration icon
            And I enable explicit staff locking
            And I click save
            Then the subsection shows a staff lock warning
            And all its descendants are staff locked
            And when I click on the subsection's configuration icon
            And I disable explicit staff locking
            And I click save
            Then the the subsection does not show a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        subsection = self.course_outline_page.section_at(0).subsection_at(0)
        self._toggle_lock_on_unlocked_item(subsection)

    def test_sections_can_be_locked(self):
        """
        Scenario: Sections can be locked and unlocked from the course outline page
            Given I have a course with a section
            When I click on the section's configuration icon
            And I enable explicit staff locking
            And I click save
            Then the section shows a staff lock warning
            And all its descendants are staff locked
            And when I click on the section's configuration icon
            And I disable explicit staff locking
            And I click save
            Then the section does not show a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        section = self.course_outline_page.section_at(0)
        self._toggle_lock_on_unlocked_item(section)

    def test_explicit_staff_lock_remains_after_unlocking_section(self):
        """
        Scenario: An explicitly locked unit is still locked after removing an inherited lock from a section
            Given I have a course with sections, subsections, and units
            And I have enabled explicit staff lock on a section and one of its units
            When I click on the section's configuration icon
            And I disable explicit staff locking
            And I click save
            Then the unit still shows a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        section = self.course_outline_page.section_at(0)
        unit = section.subsection_at(0).unit_at(0)
        self._verify_explicit_staff_lock_remains_after_unlocking_parent(unit, section)

    def test_explicit_staff_lock_remains_after_unlocking_subsection(self):
        """
        Scenario: An explicitly locked unit is still locked after removing an inherited lock from a subsection
            Given I have a course with sections, subsections, and units
            And I have enabled explicit staff lock on a subsection and one of its units
            When I click on the subsection's configuration icon
            And I disable explicit staff locking
            And I click save
            Then the unit still shows a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        subsection = self.course_outline_page.section_at(0).subsection_at(0)
        unit = subsection.unit_at(0)
        self._verify_explicit_staff_lock_remains_after_unlocking_parent(unit, subsection)

    def test_section_displays_lock_when_all_subsections_locked(self):
        """
        Scenario: All subsections in section are explicitly locked, section should display staff only warning
            Given I have a course one section and two subsections
            When I enable explicit staff lock on all the subsections
            Then the section shows a staff lock warning
        """
        self.course_outline_page.visit()
        section = self.course_outline_page.section_at(0)
        section.subsection_at(0).set_staff_lock(True)
        section.subsection_at(1).set_staff_lock(True)
        self.assertTrue(section.has_staff_lock_warning)

    def test_section_displays_lock_when_all_units_locked(self):
        """
        Scenario: All units in a section are explicitly locked, section should display staff only warning
            Given I have a course with one section, two subsections, and four units
            When I enable explicit staff lock on all the units
            Then the section shows a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        section = self.course_outline_page.section_at(0)
        section.subsection_at(0).unit_at(0).set_staff_lock(True)
        section.subsection_at(0).unit_at(1).set_staff_lock(True)
        section.subsection_at(1).unit_at(0).set_staff_lock(True)
        section.subsection_at(1).unit_at(1).set_staff_lock(True)
        self.assertTrue(section.has_staff_lock_warning)

    def test_subsection_displays_lock_when_all_units_locked(self):
        """
        Scenario: All units in subsection are explicitly locked, subsection should display staff only warning
            Given I have a course with one subsection and two units
            When I enable explicit staff lock on all the units
            Then the subsection shows a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        subsection = self.course_outline_page.section_at(0).subsection_at(0)
        subsection.unit_at(0).set_staff_lock(True)
        subsection.unit_at(1).set_staff_lock(True)
        self.assertTrue(subsection.has_staff_lock_warning)

    def test_section_does_not_display_lock_when_some_subsections_locked(self):
        """
        Scenario: Only some subsections in section are explicitly locked, section should NOT display staff only warning
            Given I have a course with one section and two subsections
            When I enable explicit staff lock on one subsection
            Then the section does not show a staff lock warning
        """
        self.course_outline_page.visit()
        section = self.course_outline_page.section_at(0)
        section.subsection_at(0).set_staff_lock(True)
        self.assertFalse(section.has_staff_lock_warning)

    def test_section_does_not_display_lock_when_some_units_locked(self):
        """
        Scenario: Only some units in section are explicitly locked, section should NOT display staff only warning
            Given I have a course with one section, two subsections, and four units
            When I enable explicit staff lock on three units
            Then the section does not show a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        section = self.course_outline_page.section_at(0)
        section.subsection_at(0).unit_at(0).set_staff_lock(True)
        section.subsection_at(0).unit_at(1).set_staff_lock(True)
        section.subsection_at(1).unit_at(1).set_staff_lock(True)
        self.assertFalse(section.has_staff_lock_warning)

    def test_subsection_does_not_display_lock_when_some_units_locked(self):
        """
        Scenario: Only some units in subsection are explicitly locked, subsection should NOT display staff only warning
            Given I have a course with one subsection and two units
            When I enable explicit staff lock on one unit
            Then the subsection does not show a staff lock warning
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        subsection = self.course_outline_page.section_at(0).subsection_at(0)
        subsection.unit_at(0).set_staff_lock(True)
        self.assertFalse(subsection.has_staff_lock_warning)

    def test_locked_sections_do_not_appear_in_lms(self):
        """
        Scenario: A locked section is not visible to students in the LMS
            Given I have a course with two sections
            When I enable explicit staff lock on one section
            And I click the View Live button to switch to staff view
            And I visit the course home with the outline
            Then I see two sections in the outline
            And when I switch the view mode to student view
            Then I see one section in the outline
        """
        self.course_outline_page.visit()
        self.course_outline_page.add_section_from_top_button()
        self.course_outline_page.section_at(1).set_staff_lock(True)
        self.course_outline_page.view_live()

        course_home_page = CourseHomePage(self.browser, self.course_id)
        course_home_page.visit()
        course_home_page.wait_for_page()
        self.assertEqual(course_home_page.outline.num_sections, 2)
        course_home_page.preview.set_staff_view_mode('Learner')
        course_home_page.wait_for(lambda: course_home_page.outline.num_sections == 1,
                                  'Only 1 section is visible in the outline')

    def test_toggling_staff_lock_on_section_does_not_publish_draft_units(self):
        """
        Scenario: Locking and unlocking a section will not publish its draft units
            Given I have a course with a section and unit
            And the unit has a draft and published version
            When I enable explicit staff lock on the section
            And I disable explicit staff lock on the section
            And I click the View Live button to switch to staff view
            Then I see the published version of the unit
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        unit = self.course_outline_page.section_at(0).subsection_at(0).unit_at(0).go_to()
        add_discussion(unit)
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        section = self.course_outline_page.section_at(0)
        section.set_staff_lock(True)
        section.set_staff_lock(False)
        unit = section.subsection_at(0).unit_at(0).go_to()
        unit.view_published_version()
        courseware = CoursewarePage(self.browser, self.course_id)
        courseware.wait_for_page()
        self.assertEqual(courseware.num_xblock_components, 0)

    def test_toggling_staff_lock_on_subsection_does_not_publish_draft_units(self):
        """
        Scenario: Locking and unlocking a subsection will not publish its draft units
            Given I have a course with a subsection and unit
            And the unit has a draft and published version
            When I enable explicit staff lock on the subsection
            And I disable explicit staff lock on the subsection
            And I click the View Live button to switch to staff view
            Then I see the published version of the unit
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        unit = self.course_outline_page.section_at(0).subsection_at(0).unit_at(0).go_to()
        add_discussion(unit)
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        subsection = self.course_outline_page.section_at(0).subsection_at(0)
        subsection.set_staff_lock(True)
        subsection.set_staff_lock(False)
        unit = subsection.unit_at(0).go_to()
        unit.view_published_version()
        courseware = CoursewarePage(self.browser, self.course_id)
        courseware.wait_for_page()
        self.assertEqual(courseware.num_xblock_components, 0)

    def test_removing_staff_lock_from_unit_without_inherited_lock_shows_warning(self):
        """
        Scenario: Removing explicit staff lock from a unit which does not inherit staff lock displays a warning.
            Given I have a course with a subsection and unit
            When I enable explicit staff lock on the unit
            And I disable explicit staff lock on the unit
            Then I see a modal warning.
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        unit = self.course_outline_page.section_at(0).subsection_at(0).unit_at(0)
        unit.set_staff_lock(True)
        self._remove_staff_lock_and_verify_warning(unit, True)

    def test_removing_staff_lock_from_subsection_without_inherited_lock_shows_warning(self):
        """
        Scenario: Removing explicit staff lock from a subsection which does not inherit staff lock displays a warning.
            Given I have a course with a section and subsection
            When I enable explicit staff lock on the subsection
            And I disable explicit staff lock on the subsection
            Then I see a modal warning.
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        subsection = self.course_outline_page.section_at(0).subsection_at(0)
        subsection.set_staff_lock(True)
        self._remove_staff_lock_and_verify_warning(subsection, True)

    def test_removing_staff_lock_from_unit_with_inherited_lock_shows_no_warning(self):
        """
        Scenario: Removing explicit staff lock from a unit which also inherits staff lock displays no warning.
            Given I have a course with a subsection and unit
            When I enable explicit staff lock on the subsection
            And I enable explicit staff lock on the unit
            When I disable explicit staff lock on the unit
            Then I do not see a modal warning.
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        subsection = self.course_outline_page.section_at(0).subsection_at(0)
        unit = subsection.unit_at(0)
        subsection.set_staff_lock(True)
        unit.set_staff_lock(True)
        self._remove_staff_lock_and_verify_warning(unit, False)

    def test_removing_staff_lock_from_subsection_with_inherited_lock_shows_no_warning(self):
        """
        Scenario: Removing explicit staff lock from a subsection which also inherits staff lock displays no warning.
            Given I have a course with a section and subsection
            When I enable explicit staff lock on the section
            And I enable explicit staff lock on the subsection
            When I disable explicit staff lock on the subsection
            Then I do not see a modal warning.
        """
        self.course_outline_page.visit()
        self.course_outline_page.expand_all_subsections()
        section = self.course_outline_page.section_at(0)
        subsection = section.subsection_at(0)
        section.set_staff_lock(True)
        subsection.set_staff_lock(True)
        self._remove_staff_lock_and_verify_warning(subsection, False)


@attr(shard=14)
class EditNamesTest(CourseOutlineTest):
    """
    Feature: Click-to-edit section/subsection names
    """

    __test__ = True

    def set_name_and_verify(self, item, old_name, new_name, expected_name):
        """
        Changes the display name of item from old_name to new_name, then verifies that its value is expected_name.
        """
        self.assertEqual(item.name, old_name)
        item.change_name(new_name)
        self.assertFalse(item.in_editable_form())
        self.assertEqual(item.name, expected_name)

    def test_edit_section_name(self):
        """
        Scenario: Click-to-edit section name
            Given that I have created a section
            When I click on the name of section
            Then the section name becomes editable
            And given that I have edited the section name
            When I click outside of the edited section name
            Then the section name saves
            And becomes non-editable
        """
        self.course_outline_page.visit()
        self.set_name_and_verify(
            self.course_outline_page.section_at(0),
            'Test Section',
            'Changed',
            'Changed'
        )

    def test_edit_subsection_name(self):
        """
        Scenario: Click-to-edit subsection name
            Given that I have created a subsection
            When I click on the name of subsection
            Then the subsection name becomes editable
            And given that I have edited the subsection name
            When I click outside of the edited subsection name
            Then the subsection name saves
            And becomes non-editable
        """
        self.course_outline_page.visit()
        self.set_name_and_verify(
            self.course_outline_page.section_at(0).subsection_at(0),
            'Test Subsection',
            'Changed',
            'Changed'
        )

    def test_edit_empty_section_name(self):
        """
        Scenario: Click-to-edit section name, enter empty name
            Given that I have created a section
            And I have clicked to edit the name of the section
            And I have entered an empty section name
            When I click outside of the edited section name
            Then the section name does not change
            And becomes non-editable
        """
        self.course_outline_page.visit()
        self.set_name_and_verify(
            self.course_outline_page.section_at(0),
            'Test Section',
            '',
            'Test Section'
        )

    def test_edit_empty_subsection_name(self):
        """
        Scenario: Click-to-edit subsection name, enter empty name
            Given that I have created a subsection
            And I have clicked to edit the name of the subsection
            And I have entered an empty subsection name
            When I click outside of the edited subsection name
            Then the subsection name does not change
            And becomes non-editable
        """
        self.course_outline_page.visit()
        self.set_name_and_verify(
            self.course_outline_page.section_at(0).subsection_at(0),
            'Test Subsection',
            '',
            'Test Subsection'
        )

    def test_editing_names_does_not_expand_collapse(self):
        """
        Scenario: A section stays in the same expand/collapse state while its name is edited
            Given that I have created a section
            And the section is collapsed
            When I click on the name of the section
            Then the section is collapsed
            And given that I have entered a new name
            Then the section is collapsed
            And given that I press ENTER to finalize the name
            Then the section is collapsed
        """
        self.course_outline_page.visit()
        self.course_outline_page.section_at(0).expand_subsection()
        self.assertFalse(self.course_outline_page.section_at(0).in_editable_form())
        self.assertTrue(self.course_outline_page.section_at(0).is_collapsed)
        self.course_outline_page.section_at(0).edit_name()
        self.assertTrue(self.course_outline_page.section_at(0).in_editable_form())
        self.assertTrue(self.course_outline_page.section_at(0).is_collapsed)
        self.course_outline_page.section_at(0).enter_name('Changed')
        self.assertTrue(self.course_outline_page.section_at(0).is_collapsed)
        self.course_outline_page.section_at(0).finalize_name()
        self.assertTrue(self.course_outline_page.section_at(0).is_collapsed)


@attr(shard=14)
class CreateSectionsTest(CourseOutlineTest):
    """
    Feature: Create new sections/subsections/units
    """

    __test__ = True

    def populate_course_fixture(self, course_fixture):
        """ Start with a completely empty course to easily test adding things to it """
        pass

    def test_create_new_section_from_top_button(self):
        """
        Scenario: Create new section from button at top of page
            Given that I am on the course outline
            When I click the "+ Add section" button at the top of the page
            Then I see a new section added to the bottom of the page
            And the display name is in its editable form.
        """
        self.course_outline_page.visit()
        self.course_outline_page.add_section_from_top_button()
        self.assertEqual(len(self.course_outline_page.sections()), 1)
        self.assertTrue(self.course_outline_page.section_at(0).in_editable_form())

    def test_create_new_section_from_bottom_button(self):
        """
        Scenario: Create new section from button at bottom of page
            Given that I am on the course outline
            When I click the "+ Add section" button at the bottom of the page
            Then I see a new section added to the bottom of the page
            And the display name is in its editable form.
        """
        self.course_outline_page.visit()
        self.course_outline_page.add_section_from_bottom_button()
        self.assertEqual(len(self.course_outline_page.sections()), 1)
        self.assertTrue(self.course_outline_page.section_at(0).in_editable_form())

    def test_create_new_section_from_bottom_button_plus_icon(self):
        """
        Scenario: Create new section from button plus icon at bottom of page
            Given that I am on the course outline
            When I click the plus icon in "+ Add section" button at the bottom of the page
            Then I see a new section added to the bottom of the page
            And the display name is in its editable form.
        """
        self.course_outline_page.visit()
        self.course_outline_page.add_section_from_bottom_button(click_child_icon=True)
        self.assertEqual(len(self.course_outline_page.sections()), 1)
        self.assertTrue(self.course_outline_page.section_at(0).in_editable_form())

    def test_create_new_subsection(self):
        """
        Scenario: Create new subsection
            Given that I have created a section
            When I click the "+ Add subsection" button in that section
            Then I see a new subsection added to the bottom of the section
            And the display name is in its editable form.
        """
        self.course_outline_page.visit()
        self.course_outline_page.add_section_from_top_button()
        self.assertEqual(len(self.course_outline_page.sections()), 1)
        self.course_outline_page.section_at(0).add_subsection()
        subsections = self.course_outline_page.section_at(0).subsections()
        self.assertEqual(len(subsections), 1)
        self.assertTrue(subsections[0].in_editable_form())

    def test_create_new_unit(self):
        """
        Scenario: Create new unit
            Given that I have created a section
            And that I have created a subsection within that section
            When I click the "+ Add unit" button in that subsection
            Then I am redirected to a New Unit page
            And the display name is in its editable form.
        """
        self.course_outline_page.visit()
        self.course_outline_page.add_section_from_top_button()
        self.assertEqual(len(self.course_outline_page.sections()), 1)
        self.course_outline_page.section_at(0).add_subsection()
        self.assertEqual(len(self.course_outline_page.section_at(0).subsections()), 1)
        self.course_outline_page.section_at(0).subsection_at(0).add_unit()
        unit_page = ContainerPage(self.browser, None)
        unit_page.wait_for_page()
        self.assertTrue(unit_page.is_inline_editing_display_name())


@attr(shard=14)
class DeleteContentTest(CourseOutlineTest):
    """
    Feature: Deleting sections/subsections/units
    """

    __test__ = True

    def test_delete_section(self):
        """
        Scenario: Delete section
            Given that I am on the course outline
            When I click the delete button for a section on the course outline
            Then I should receive a confirmation message, asking me if I really want to delete the section
            When I click "Yes, I want to delete this component"
            Then the confirmation message should close
            And the section should immediately be deleted from the course outline
        """
        self.course_outline_page.visit()
        self.assertEqual(len(self.course_outline_page.sections()), 1)
        self.course_outline_page.section_at(0).delete()
        self.assertEqual(len(self.course_outline_page.sections()), 0)

    def test_cancel_delete_section(self):
        """
        Scenario: Cancel delete of section
            Given that I clicked the delte button for a section on the course outline
            And I received a confirmation message, asking me if I really want to delete the component
            When I click "Cancel"
            Then the confirmation message should close
            And the section should remain in the course outline
        """
        self.course_outline_page.visit()
        self.assertEqual(len(self.course_outline_page.sections()), 1)
        self.course_outline_page.section_at(0).delete(cancel=True)
        self.assertEqual(len(self.course_outline_page.sections()), 1)

    def test_delete_subsection(self):
        """
        Scenario: Delete subsection
            Given that I am on the course outline
            When I click the delete button for a subsection on the course outline
            Then I should receive a confirmation message, asking me if I really want to delete the subsection
            When I click "Yes, I want to delete this component"
            Then the confiramtion message should close
            And the subsection should immediately be deleted from the course outline
        """
        self.course_outline_page.visit()
        self.assertEqual(len(self.course_outline_page.section_at(0).subsections()), 1)
        self.course_outline_page.section_at(0).subsection_at(0).delete()
        self.assertEqual(len(self.course_outline_page.section_at(0).subsections()), 0)

    def test_cancel_delete_subsection(self):
        """
        Scenario: Cancel delete of subsection
            Given that I clicked the delete button for a subsection on the course outline
            And I received a confirmation message, asking me if I really want to delete the subsection
            When I click "cancel"
            Then the confirmation message should close
            And the subsection should remain in the course outline
        """
        self.course_outline_page.visit()
        self.assertEqual(len(self.course_outline_page.section_at(0).subsections()), 1)
        self.course_outline_page.section_at(0).subsection_at(0).delete(cancel=True)
        self.assertEqual(len(self.course_outline_page.section_at(0).subsections()), 1)

    def test_delete_unit(self):
        """
        Scenario: Delete unit
            Given that I am on the course outline
            When I click the delete button for a unit on the course outline
            Then I should receive a confirmation message, asking me if I really want to delete the unit
            When I click "Yes, I want to delete this unit"
            Then the confirmation message should close
            And the unit should immediately be deleted from the course outline
        """
        self.course_outline_page.visit()
        self.course_outline_page.section_at(0).subsection_at(0).expand_subsection()
        self.assertEqual(len(self.course_outline_page.section_at(0).subsection_at(0).units()), 1)
        self.course_outline_page.section_at(0).subsection_at(0).unit_at(0).delete()
        self.assertEqual(len(self.course_outline_page.section_at(0).subsection_at(0).units()), 0)

    def test_cancel_delete_unit(self):
        """
        Scenario: Cancel delete of unit
            Given that I clicked the delete button for a unit on the course outline
            And I received a confirmation message, asking me if I really want to delete the unit
            When I click "Cancel"
            Then the confirmation message should close
            And the unit should remain in the course outline
        """
        self.course_outline_page.visit()
        self.course_outline_page.section_at(0).subsection_at(0).expand_subsection()
        self.assertEqual(len(self.course_outline_page.section_at(0).subsection_at(0).units()), 1)
        self.course_outline_page.section_at(0).subsection_at(0).unit_at(0).delete(cancel=True)
        self.assertEqual(len(self.course_outline_page.section_at(0).subsection_at(0).units()), 1)

    def test_delete_all_no_content_message(self):
        """
        Scenario: Delete all sections/subsections/units in a course, "no content" message should appear
            Given that I delete all sections, subsections, and units in a course
            When I visit the course outline
            Then I will see a message that says, "You haven't added any content to this course yet"
            Add see a + Add Section button
        """
        self.course_outline_page.visit()
        self.assertFalse(self.course_outline_page.has_no_content_message)
        self.course_outline_page.section_at(0).delete()
        self.assertEqual(len(self.course_outline_page.sections()), 0)
        self.assertTrue(self.course_outline_page.has_no_content_message)


@attr(shard=14)
class ExpandCollapseMultipleSectionsTest(CourseOutlineTest):
    """
    Feature: Courses with multiple sections can expand and collapse all sections.
    """

    __test__ = True

    def populate_course_fixture(self, course_fixture):
        """ Start with a course with two sections """
        course_fixture.add_children(
            XBlockFixtureDesc('chapter', 'Test Section').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection').add_children(
                    XBlockFixtureDesc('vertical', 'Test Unit')
                )
            ),
            XBlockFixtureDesc('chapter', 'Test Section 2').add_children(
                XBlockFixtureDesc('sequential', 'Test Subsection 2').add_children(
                    XBlockFixtureDesc('vertical', 'Test Unit 2')
                )
            )
        )

    def verify_all_sections(self, collapsed):
        """
        Verifies that all sections are collapsed if collapsed is True, otherwise all expanded.
        """
        for section in self.course_outline_page.sections():
            self.assertEqual(collapsed, section.is_collapsed)

    def toggle_all_sections(self):
        """
        Toggles the expand collapse state of all sections.
        """
        for section in self.course_outline_page.sections():
            section.expand_subsection()

    def test_expanded_by_default(self):
        """
        Scenario: The default layout for the outline page is to show sections in expanded view
            Given I have a course with sections
            When I navigate to the course outline page
            Then I see the "Collapse All Sections" link
            And all sections are expanded
        """
        self.course_outline_page.visit()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.COLLAPSE)
        self.verify_all_sections(collapsed=False)

    def test_no_expand_link_for_empty_course(self):
        """
        Scenario: Collapse link is removed after last section of a course is deleted
            Given I have a course with multiple sections
            And I navigate to the course outline page
            When I will confirm all alerts
            And I press the "section" delete icon
            Then I do not see the "Collapse All Sections" link
            And I will see a message that says "You haven't added any content to this course yet"
        """
        self.course_outline_page.visit()
        for section in self.course_outline_page.sections():
            section.delete()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.MISSING)
        self.assertTrue(self.course_outline_page.has_no_content_message)

    def test_collapse_all_when_all_expanded(self):
        """
        Scenario: Collapse all sections when all sections are expanded
            Given I navigate to the outline page of a course with sections
            And all sections are expanded
            When I click the "Collapse All Sections" link
            Then I see the "Expand All Sections" link
            And all sections are collapsed
        """
        self.course_outline_page.visit()
        self.verify_all_sections(collapsed=False)
        self.course_outline_page.toggle_expand_collapse()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.EXPAND)
        self.verify_all_sections(collapsed=True)

    def test_collapse_all_when_some_expanded(self):
        """
        Scenario: Collapsing all sections when 1 or more sections are already collapsed
            Given I navigate to the outline page of a course with sections
            And all sections are expanded
            When I collapse the first section
            And I click the "Collapse All Sections" link
            Then I see the "Expand All Sections" link
            And all sections are collapsed
        """
        self.course_outline_page.visit()
        self.verify_all_sections(collapsed=False)
        self.course_outline_page.section_at(0).expand_subsection()
        self.course_outline_page.toggle_expand_collapse()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.EXPAND)
        self.verify_all_sections(collapsed=True)

    def test_expand_all_when_all_collapsed(self):
        """
        Scenario: Expanding all sections when all sections are collapsed
            Given I navigate to the outline page of a course with multiple sections
            And I click the "Collapse All Sections" link
            When I click the "Expand All Sections" link
            Then I see the "Collapse All Sections" link
            And all sections are expanded
        """
        self.course_outline_page.visit()
        self.course_outline_page.toggle_expand_collapse()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.EXPAND)
        self.course_outline_page.toggle_expand_collapse()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.COLLAPSE)
        self.verify_all_sections(collapsed=False)

    @skip('Edraak: Could not run on Jenkins')
    def test_expand_all_when_some_collapsed(self):
        """
        Scenario: Expanding all sections when 1 or more sections are already expanded
            Given I navigate to the outline page of a course with multiple sections
            And I click the "Collapse All Sections" link
            When I expand the first section
            And I click the "Expand All Sections" link
            Then I see the "Collapse All Sections" link
            And all sections are expanded
        """
        self.course_outline_page.visit()
        # We have seen unexplainable sporadic failures in this test. Try disabling animations to see
        # if that helps.
        disable_animations(self.course_outline_page)
        self.course_outline_page.toggle_expand_collapse()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.EXPAND)
        self.verify_all_sections(collapsed=True)
        self.course_outline_page.section_at(0).expand_subsection()
        self.course_outline_page.toggle_expand_collapse()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.COLLAPSE)
        self.verify_all_sections(collapsed=False)


@attr(shard=14)
class ExpandCollapseSingleSectionTest(CourseOutlineTest):
    """
    Feature: Courses with a single section can expand and collapse all sections.
    """

    __test__ = True

    def test_no_expand_link_for_empty_course(self):
        """
        Scenario: Collapse link is removed after last section of a course is deleted
            Given I have a course with one section
            And I navigate to the course outline page
            When I will confirm all alerts
            And I press the "section" delete icon
            Then I do not see the "Collapse All Sections" link
            And I will see a message that says "You haven't added any content to this course yet"
        """
        self.course_outline_page.visit()
        self.course_outline_page.section_at(0).delete()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.MISSING)
        self.assertTrue(self.course_outline_page.has_no_content_message)

    def test_old_subsection_stays_collapsed_after_creation(self):
        """
        Scenario: Collapsed subsection stays collapsed after creating a new subsection
            Given I have a course with one section and subsection
            And I navigate to the course outline page
            Then the subsection is collapsed
            And when I create a new subsection
            Then the first subsection is collapsed
            And the second subsection is expanded
        """
        self.course_outline_page.visit()
        self.assertTrue(self.course_outline_page.section_at(0).subsection_at(0).is_collapsed)
        self.course_outline_page.section_at(0).add_subsection()
        self.assertTrue(self.course_outline_page.section_at(0).subsection_at(0).is_collapsed)
        self.assertFalse(self.course_outline_page.section_at(0).subsection_at(1).is_collapsed)


@attr(shard=14)
class ExpandCollapseEmptyTest(CourseOutlineTest):
    """
    Feature: Courses with no sections initially can expand and collapse all sections after addition.
    """

    __test__ = True

    def populate_course_fixture(self, course_fixture):
        """ Start with an empty course """
        pass

    def test_no_expand_link_for_empty_course(self):
        """
        Scenario: Expand/collapse for a course with no sections
            Given I have a course with no sections
            When I navigate to the course outline page
            Then I do not see the "Collapse All Sections" link
        """
        self.course_outline_page.visit()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.MISSING)

    def test_link_appears_after_section_creation(self):
        """
        Scenario: Collapse link appears after creating first section of a course
            Given I have a course with no sections
            When I navigate to the course outline page
            And I add a section
            Then I see the "Collapse All Sections" link
            And all sections are expanded
        """
        self.course_outline_page.visit()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.MISSING)
        self.course_outline_page.add_section_from_top_button()
        self.assertEquals(self.course_outline_page.expand_collapse_link_state, ExpandCollapseLinkState.COLLAPSE)
        self.assertFalse(self.course_outline_page.section_at(0).is_collapsed)


@attr(shard=14)
class DefaultStatesEmptyTest(CourseOutlineTest):
    """
    Feature: Misc course outline default states/actions when starting with an empty course
    """

    __test__ = True

    def populate_course_fixture(self, course_fixture):
        """ Start with an empty course """
        pass

    def test_empty_course_message(self):
        """
        Scenario: Empty course state
            Given that I am in a course with no sections, subsections, nor units
            When I visit the course outline
            Then I will see a message that says "You haven't added any content to this course yet"
            And see a + Add Section button
        """
        self.course_outline_page.visit()
        self.assertTrue(self.course_outline_page.has_no_content_message)
        self.assertTrue(self.course_outline_page.bottom_add_section_button.is_present())


@attr(shard=14)
class DefaultStatesContentTest(CourseOutlineTest):
    """
    Feature: Misc course outline default states/actions when starting with a course with content
    """

    __test__ = True

    def test_view_live(self):
        """
        Scenario: View Live version from course outline
            Given that I am on the course outline
            When I click the "View Live" button
            Then a new tab will open to the course on the LMS
        """
        self.course_outline_page.visit()
        self.course_outline_page.view_live()
        courseware = CoursewarePage(self.browser, self.course_id)
        courseware.wait_for_page()
        self.assertEqual(courseware.num_xblock_components, 3)
        self.assertEqual(courseware.xblock_component_type(0), 'problem')
        self.assertEqual(courseware.xblock_component_type(1), 'html')
        self.assertEqual(courseware.xblock_component_type(2), 'discussion')


@attr(shard=7)
class UnitNavigationTest(CourseOutlineTest):
    """
    Feature: Navigate to units
    """

    __test__ = True

    def test_navigate_to_unit(self):
        """
        Scenario: Click unit name to navigate to unit page
            Given that I have expanded a section/subsection so I can see unit names
            When I click on a unit name
            Then I will be taken to the appropriate unit page
        """
        self.course_outline_page.visit()
        self.course_outline_page.section_at(0).subsection_at(0).expand_subsection()
        unit = self.course_outline_page.section_at(0).subsection_at(0).unit_at(0).go_to()
        unit.wait_for_page()


@attr(shard=7)
class PublishSectionTest(CourseOutlineTest):
    """
    Feature: Publish sections.
    """

    __test__ = True

    def populate_course_fixture(self, course_fixture):
        """
        Sets up a course structure with 2 subsections inside a single section.
        The first subsection has 2 units, and the second subsection has one unit.
        """
        self.courseware = CoursewarePage(self.browser, self.course_id)
        self.course_home_page = CourseHomePage(self.browser, self.course_id)
        course_fixture.add_children(
            XBlockFixtureDesc('chapter', SECTION_NAME).add_children(
                XBlockFixtureDesc('sequential', SUBSECTION_NAME).add_children(
                    XBlockFixtureDesc('vertical', UNIT_NAME),
                    XBlockFixtureDesc('vertical', 'Test Unit 2'),
                ),
                XBlockFixtureDesc('sequential', 'Test Subsection 2').add_children(
                    XBlockFixtureDesc('vertical', 'Test Unit 3'),
                ),
            ),
        )

    def test_unit_publishing(self):
        """
        Scenario: Can publish a unit and see published content in LMS
            Given I have a section with 2 subsections and 3 unpublished units
            When I go to the course outline
            Then I see publish button for the first unit, subsection, section
            When I publish the first unit
            Then I see that publish button for the first unit disappears
            And I see publish buttons for subsection, section
            And I see the changed content in LMS
        """
        self._add_unpublished_content()
        self.course_outline_page.visit()
        section, subsection, unit = self._get_items()
        self.assertTrue(unit.publish_action)
        self.assertTrue(subsection.publish_action)
        self.assertTrue(section.publish_action)
        unit.publish()
        self.assertFalse(unit.publish_action)
        self.assertTrue(subsection.publish_action)
        self.assertTrue(section.publish_action)
        self.courseware.visit()
        self.assertEqual(1, self.courseware.num_xblock_components)

    def test_subsection_publishing(self):
        """
        Scenario: Can publish a subsection and see published content in LMS
            Given I have a section with 2 subsections and 3 unpublished units
            When I go to the course outline
            Then I see publish button for the unit, subsection, section
            When I publish the first subsection
            Then I see that publish button for the first subsection disappears
            And I see that publish buttons disappear for the child units of the subsection
            And I see publish button for section
            And I see the changed content in LMS
        """
        self._add_unpublished_content()
        self.course_outline_page.visit()
        section, subsection, unit = self._get_items()
        self.assertTrue(unit.publish_action)
        self.assertTrue(subsection.publish_action)
        self.assertTrue(section.publish_action)
        self.course_outline_page.section(SECTION_NAME).subsection(SUBSECTION_NAME).publish()
        self.assertFalse(unit.publish_action)
        self.assertFalse(subsection.publish_action)
        self.assertTrue(section.publish_action)
        self.courseware.visit()
        self.assertEqual(1, self.courseware.num_xblock_components)
        self.courseware.go_to_sequential_position(2)
        self.assertEqual(1, self.courseware.num_xblock_components)

    def test_section_publishing(self):
        """
        Scenario: Can publish a section and see published content in LMS
            Given I have a section with 2 subsections and 3 unpublished units
            When I go to the course outline
            Then I see publish button for the unit, subsection, section
            When I publish the section
            Then I see that publish buttons disappears
            And I see the changed content in LMS
        """
        self._add_unpublished_content()
        self.course_outline_page.visit()
        section, subsection, unit = self._get_items()
        self.assertTrue(subsection.publish_action)
        self.assertTrue(section.publish_action)
        self.assertTrue(unit.publish_action)
        self.course_outline_page.section(SECTION_NAME).publish()
        self.assertFalse(subsection.publish_action)
        self.assertFalse(section.publish_action)
        self.assertFalse(unit.publish_action)
        self.courseware.visit()
        self.assertEqual(1, self.courseware.num_xblock_components)
        self.courseware.go_to_sequential_position(2)
        self.assertEqual(1, self.courseware.num_xblock_components)
        self.course_home_page.visit()
        self.course_home_page.outline.go_to_section(SECTION_NAME, 'Test Subsection 2')
        self.assertEqual(1, self.courseware.num_xblock_components)

    def _add_unpublished_content(self):
        """
        Adds unpublished HTML content to first three units in the course.
        """
        for index in xrange(3):
            self.course_fixture.create_xblock(
                self.course_fixture.get_nested_xblocks(category="vertical")[index].locator,
                XBlockFixtureDesc('html', 'Unpublished HTML Component ' + str(index)),
            )

    def _get_items(self):
        """
        Returns first section, subsection, and unit on the page.
        """
        section = self.course_outline_page.section(SECTION_NAME)
        subsection = section.subsection(SUBSECTION_NAME)
        unit = subsection.expand_subsection().unit(UNIT_NAME)

        return (section, subsection, unit)


@attr(shard=7)
class DeprecationWarningMessageTest(CourseOutlineTest):
    """
    Feature: Verify deprecation warning message.
    """
    HEADING_TEXT = 'This course uses features that are no longer supported.'
    COMPONENT_LIST_HEADING = 'You must delete or replace the following components.'
    ADVANCE_MODULES_REMOVE_TEXT = (
        u'To avoid errors, édX strongly recommends that you remove unsupported features '
        u'from the course advanced settings. To do this, go to the Advanced Settings '
        u'page, locate the "Advanced Module List" setting, and then delete the following '
        u'modules from the list.'
    )
    DEFAULT_DISPLAYNAME = "Deprecated Component"

    def _add_deprecated_advance_modules(self, block_types):
        """
        Add `block_types` into `Advanced Module List`

        Arguments:
            block_types (list): list of block types
        """
        self.advanced_settings.visit()
        self.advanced_settings.set_values({"Advanced Module List": json.dumps(block_types)})

    def _create_deprecated_components(self):
        """
        Create deprecated components.
        """
        parent_vertical = self.course_fixture.get_nested_xblocks(category="vertical")[0]

        self.course_fixture.create_xblock(
            parent_vertical.locator,
            XBlockFixtureDesc('poll', "Poll", data=load_data_str('poll_markdown.xml'))
        )
        self.course_fixture.create_xblock(parent_vertical.locator, XBlockFixtureDesc('survey', 'Survey'))

    def _verify_deprecation_warning_info(
            self,
            deprecated_blocks_present,
            components_present,
            components_display_name_list=None,
            deprecated_modules_list=None
    ):
        """
        Verify deprecation warning

        Arguments:
            deprecated_blocks_present (bool): deprecated blocks remove text and
                is list is visible if True else False
            components_present (bool): components list shown if True else False
            components_display_name_list (list): list of components display name
            deprecated_modules_list (list): list of deprecated advance modules
        """
        self.assertTrue(self.course_outline_page.deprecated_warning_visible)
        self.assertEqual(self.course_outline_page.warning_heading_text, self.HEADING_TEXT)
        self.assertEqual(self.course_outline_page.modules_remove_text_shown, deprecated_blocks_present)
        if deprecated_blocks_present:
            self.assertEqual(self.course_outline_page.modules_remove_text, self.ADVANCE_MODULES_REMOVE_TEXT)
            self.assertEqual(self.course_outline_page.deprecated_advance_modules, deprecated_modules_list)

        self.assertEqual(self.course_outline_page.components_visible, components_present)
        if components_present:
            self.assertEqual(self.course_outline_page.components_list_heading, self.COMPONENT_LIST_HEADING)
            self.assertItemsEqual(self.course_outline_page.components_display_names, components_display_name_list)

    def test_no_deprecation_warning_message_present(self):
        """
        Scenario: Verify that deprecation warning message is not shown if no deprecated
            advance modules are not present and also no deprecated component exist in
            course outline.

        When I goto course outline
        Then I don't see any deprecation warning
        """
        self.course_outline_page.visit()
        self.assertFalse(self.course_outline_page.deprecated_warning_visible)

    def test_deprecation_warning_message_present(self):
        """
        Scenario: Verify deprecation warning message if deprecated modules
            and components are present.

        Given I have "poll" advance modules present in `Advanced Module List`
        And I have created 2 poll components
        When I go to course outline
        Then I see poll deprecated warning
        And I see correct poll deprecated warning heading text
        And I see correct poll deprecated warning advance modules remove text
        And I see list of poll components with correct display names
        """
        self._add_deprecated_advance_modules(block_types=['poll', 'survey'])
        self._create_deprecated_components()
        self.course_outline_page.visit()
        self._verify_deprecation_warning_info(
            deprecated_blocks_present=True,
            components_present=True,
            components_display_name_list=['Poll', 'Survey'],
            deprecated_modules_list=['poll', 'survey']
        )

    def test_deprecation_warning_with_no_displayname(self):
        """
        Scenario: Verify deprecation warning message if poll components are present.

        Given I have created 1 poll deprecated component
        When I go to course outline
        Then I see poll deprecated warning
        And I see correct poll deprecated warning heading text
        And I see list of poll components with correct message
        """
        parent_vertical = self.course_fixture.get_nested_xblocks(category="vertical")[0]

        # Create a deprecated component with display_name to be empty and make sure
        # the deprecation warning is displayed with
        self.course_fixture.create_xblock(
            parent_vertical.locator,
            XBlockFixtureDesc(category='poll', display_name="", data=load_data_str('poll_markdown.xml'))
        )
        self.course_outline_page.visit()

        self._verify_deprecation_warning_info(
            deprecated_blocks_present=False,
            components_present=True,
            components_display_name_list=[self.DEFAULT_DISPLAYNAME],
        )

    def test_warning_with_poll_advance_modules_only(self):
        """
        Scenario: Verify that deprecation warning message is shown if only
            poll advance modules are present and no poll component exist.

        Given I have poll advance modules present in `Advanced Module List`
        When I go to course outline
        Then I see poll deprecated warning
        And I see correct poll deprecated warning heading text
        And I see correct poll deprecated warning advance modules remove text
        And I don't see list of poll components
        """
        self._add_deprecated_advance_modules(block_types=['poll', 'survey'])
        self.course_outline_page.visit()
        self._verify_deprecation_warning_info(
            deprecated_blocks_present=True,
            components_present=False,
            deprecated_modules_list=['poll', 'survey']
        )

    def test_warning_with_poll_components_only(self):
        """
        Scenario: Verify that deprecation warning message is shown if only
            poll component exist and no poll advance modules are present.

        Given I have created two poll components
        When I go to course outline
        Then I see poll deprecated warning
        And I see correct poll deprecated warning heading text
        And I don't see poll deprecated warning advance modules remove text
        And I see list of poll components with correct display names
        """
        self._create_deprecated_components()
        self.course_outline_page.visit()
        self._verify_deprecation_warning_info(
            deprecated_blocks_present=False,
            components_present=True,
            components_display_name_list=['Poll', 'Survey']
        )


@attr(shard=4)
class SelfPacedOutlineTest(CourseOutlineTest):
    """Test the course outline for a self-paced course."""

    def populate_course_fixture(self, course_fixture):
        course_fixture.add_children(
            XBlockFixtureDesc('chapter', SECTION_NAME).add_children(
                XBlockFixtureDesc('sequential', SUBSECTION_NAME).add_children(
                    XBlockFixtureDesc('vertical', UNIT_NAME)
                )
            ),
        )
        self.course_fixture.add_course_details({
            'self_paced': True,
            'start_date': datetime.now() + timedelta(days=1)
        })
        ConfigModelFixture('/config/self_paced', {'enabled': True}).install()

    def test_release_dates_not_shown(self):
        """
        Scenario: Ensure that block release dates are not shown on the
            course outline page of a self-paced course.

        Given I am the author of a self-paced course
        When I go to the course outline
        Then I should not see release dates for course content
        """
        self.course_outline_page.visit()
        section = self.course_outline_page.section(SECTION_NAME)
        self.assertEqual(section.release_date, '')
        subsection = section.subsection(SUBSECTION_NAME)
        self.assertEqual(subsection.release_date, '')

    def test_edit_section_and_subsection(self):
        """
        Scenario: Ensure that block release/due dates are not shown
            in their settings modals.

        Given I am the author of a self-paced course
        When I go to the course outline
        And I click on settings for a section or subsection
        Then I should not see release or due date settings
        """
        self.course_outline_page.visit()
        section = self.course_outline_page.section(SECTION_NAME)
        modal = section.edit()
        self.assertFalse(modal.has_release_date())
        self.assertFalse(modal.has_due_date())
        modal.cancel()
        subsection = section.subsection(SUBSECTION_NAME)
        modal = subsection.edit()
        self.assertFalse(modal.has_release_date())
        self.assertFalse(modal.has_due_date())


class CourseStatusOutlineTest(CourseOutlineTest):
    """Test the course outline status section."""

    def setUp(self):
        super(CourseStatusOutlineTest, self).setUp()

        self.schedule_and_details_settings = SettingsPage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

        self.checklists = CourseChecklistsPage(
            self.browser,
            self.course_info['org'],
            self.course_info['number'],
            self.course_info['run']
        )

    def test_course_status_section(self):
        """
        Ensure that the course status section appears in the course outline.
        """
        self.course_outline_page.visit()
        self.assertTrue(self.course_outline_page.has_course_status_section)

    def test_course_status_section_start_date_link(self):
        """
        Ensure that the course start date link in the course status section in
        the course outline links to the "Schedule and Details" page.
        """
        self.course_outline_page.visit()
        self.course_outline_page.click_course_status_section_start_date_link()
        self.schedule_and_details_settings.wait_for_page()

    def test_course_status_section_checklists_link(self):
        """
        Ensure that the course checklists link in the course status section in
        the course outline links to the "Checklists" page.
        """
        self.course_outline_page.visit()
        self.course_outline_page.click_course_status_section_checklists_link()
        self.checklists.wait_for_page()


class InstructorPacedToSelfPacedOutlineTest(CourseOutlineTest):
    """
    Test the course outline when pacing is changed from
    instructor to self paced.
    """
    def populate_course_fixture(self, course_fixture):
        course_fixture.add_children(
            XBlockFixtureDesc('chapter', SECTION_NAME).add_children(
                XBlockFixtureDesc('sequential', SUBSECTION_NAME).add_children(
                    XBlockFixtureDesc('vertical', UNIT_NAME)
                )
            ),
        )
        self.course_fixture.add_course_details({
            'start_date': datetime.now() + timedelta(days=1),
        })
        self.course_fixture.add_advanced_settings({
            'enable_timed_exams': {
                'value': True
            }
        })

    def test_due_dates_not_shown(self):
        """
        Scenario: Ensure that due dates for timed exams
            are not displayed on the course outline page when switched to
            self-paced mode from instructor-paced.

        Given an instructor paced course, add a due date for a subsection.
        Change the course's pacing to self-paced.
        Make the subsection a timed exam.
        Make sure adding the timed exam doesn't display the due date.
        """
        self.course_outline_page.visit()
        section = self.course_outline_page.section(SECTION_NAME)
        subsection = section.subsection(SUBSECTION_NAME)

        modal = subsection.edit()
        modal.due_date = '5/14/2016'
        modal.policy = 'Homework'
        modal.save()
        # Checking if the added due date saved
        self.assertIn('May 14', subsection.due_date)
        # Checking if grading policy added
        self.assertEqual('Homework', subsection.policy)

        # Updating the course mode to self-paced
        self.course_fixture.add_course_details({
            'self_paced': True
        })
        # Making the subsection a timed exam
        self.course_outline_page.open_subsection_settings_dialog()
        self.course_outline_page.select_advanced_tab()
        self.course_outline_page.make_exam_timed()

        # configure call to actually update course with new settings
        self.course_fixture.configure_course()
        # Reloading page after the changes
        self.course_outline_page.visit()
        self.assertIsNone(subsection.due_date)
