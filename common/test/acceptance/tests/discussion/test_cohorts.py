"""
Tests related to the cohorting feature.
"""
from uuid import uuid4

from common.test.acceptance.fixtures.course import CourseFixture, XBlockFixtureDesc
from common.test.acceptance.pages.common.auto_auth import AutoAuthPage
from common.test.acceptance.pages.lms.courseware import CoursewarePage
from common.test.acceptance.pages.lms.discussion import DiscussionTabSingleThreadPage, InlineDiscussionPage
from common.test.acceptance.tests.discussion.helpers import BaseDiscussionMixin, BaseDiscussionTestCase, CohortTestMixin
from common.test.acceptance.tests.helpers import UniqueCourseTest
from openedx.core.lib.tests import attr


class NonCohortedDiscussionTestMixin(BaseDiscussionMixin):
    """
    Mixin for tests of discussion in non-cohorted courses.
    """
    def setup_cohorts(self):
        """
        No cohorts are desired for this mixin.
        """
        pass

    def test_non_cohort_visibility_label(self):
        self.setup_thread(1)
        self.assertEquals(self.thread_page.get_group_visibility_label(), "This post is visible to everyone.")


class CohortedDiscussionTestMixin(BaseDiscussionMixin, CohortTestMixin):
    """
    Mixin for tests of discussion in cohorted courses.
    """
    def setup_cohorts(self):
        """
        Sets up the course to use cohorting with a single defined cohort.
        """
        self.setup_cohort_config(self.course_fixture)
        self.cohort_1_name = "Cohort 1"
        self.cohort_1_id = self.add_manual_cohort(self.course_fixture, self.cohort_1_name)

    def test_cohort_visibility_label(self):
        # Must be moderator to view content in a cohort other than your own
        AutoAuthPage(self.browser, course_id=self.course_id, roles="Moderator").visit()
        self.thread_id = self.setup_thread(1, group_id=self.cohort_1_id)

        # Enable cohorts and verify that the post shows to cohort only.
        self.enable_cohorting(self.course_fixture)
        self.enable_always_divide_inline_discussions(self.course_fixture)
        self.refresh_thread_page(self.thread_id)
        self.assertEquals(
            self.thread_page.get_group_visibility_label(),
            "This post is visible only to {}.".format(self.cohort_1_name)
        )

        # Disable cohorts and verify that the post now shows as visible to everyone.
        self.disable_cohorting(self.course_fixture)
        self.refresh_thread_page(self.thread_id)
        self.assertEquals(self.thread_page.get_group_visibility_label(), "This post is visible to everyone.")


class DiscussionTabSingleThreadTest(BaseDiscussionTestCase):
    """
    Tests for the discussion page displaying a single thread.
    """
    def setUp(self):
        super(DiscussionTabSingleThreadTest, self).setUp()
        self.setup_cohorts()
        AutoAuthPage(self.browser, course_id=self.course_id).visit()

    def setup_thread_page(self, thread_id):
        self.thread_page = DiscussionTabSingleThreadPage(self.browser, self.course_id, self.discussion_id, thread_id)  # pylint: disable=attribute-defined-outside-init
        self.thread_page.visit()

    # pylint: disable=unused-argument
    def refresh_thread_page(self, thread_id):
        self.browser.refresh()
        self.thread_page.wait_for_page()


@attr(shard=5)
class CohortedDiscussionTabSingleThreadTest(DiscussionTabSingleThreadTest, CohortedDiscussionTestMixin):
    """
    Tests for the discussion page displaying a single cohorted thread.
    """
    # Actual test method(s) defined in CohortedDiscussionTestMixin.
    pass


@attr(shard=5)
class NonCohortedDiscussionTabSingleThreadTest(DiscussionTabSingleThreadTest, NonCohortedDiscussionTestMixin):
    """
    Tests for the discussion page displaying a single non-cohorted thread.
    """
    # Actual test method(s) defined in NonCohortedDiscussionTestMixin.
    pass


class InlineDiscussionTest(UniqueCourseTest):
    """
    Tests for inline discussions
    """
    def setUp(self):
        super(InlineDiscussionTest, self).setUp()
        self.discussion_id = "test_discussion_{}".format(uuid4().hex)
        self.course_fixture = CourseFixture(**self.course_info).add_children(
            XBlockFixtureDesc("chapter", "Test Section").add_children(
                XBlockFixtureDesc("sequential", "Test Subsection").add_children(
                    XBlockFixtureDesc("vertical", "Test Unit").add_children(
                        XBlockFixtureDesc(
                            "discussion",
                            "Test Discussion",
                            metadata={"discussion_id": self.discussion_id}
                        )
                    )
                )
            )
        ).install()
        self.setup_cohorts()

        self.user_id = AutoAuthPage(self.browser, course_id=self.course_id).visit().get_user_id()

    def setup_thread_page(self, thread_id):
        CoursewarePage(self.browser, self.course_id).visit()
        self.show_thread(thread_id)

    def show_thread(self, thread_id):
        discussion_page = InlineDiscussionPage(self.browser, self.discussion_id)
        if not discussion_page.is_discussion_expanded():
            discussion_page.expand_discussion()
        self.assertEqual(discussion_page.get_num_displayed_threads(), 1)
        discussion_page.show_thread(thread_id)
        self.thread_page = discussion_page.thread_page  # pylint: disable=attribute-defined-outside-init

    def refresh_thread_page(self, thread_id):
        self.browser.refresh()
        self.show_thread(thread_id)


@attr(shard=5)
class CohortedInlineDiscussionTest(InlineDiscussionTest, CohortedDiscussionTestMixin):
    """
    Tests for cohorted inline discussions.
    """
    # Actual test method(s) defined in CohortedDiscussionTestMixin.
    pass


@attr(shard=5)
class NonCohortedInlineDiscussionTest(InlineDiscussionTest, NonCohortedDiscussionTestMixin):
    """
    Tests for non-cohorted inline discussions.
    """
    # Actual test method(s) defined in NonCohortedDiscussionTestMixin.
    pass
