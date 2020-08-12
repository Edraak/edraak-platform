"""
Integration tests for gated content.
"""
import ddt
from crum import set_current_request
from completion import waffle as completion_waffle
from edx_django_utils.cache import RequestCache
from milestones import api as milestones_api
from milestones.tests.utils import MilestonesTestCaseMixin

from lms.djangoapps.courseware.access import has_access
from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lms.djangoapps.grades.tests.utils import answer_problem
from openedx.core.djangolib.testing.utils import get_mock_request
from openedx.core.lib.gating import api as gating_api
from student.tests.factories import UserFactory
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory


@ddt.ddt
class TestGatedContent(MilestonesTestCaseMixin, SharedModuleStoreTestCase):
    """
    Base TestCase class for setting up a basic course structure
    and testing the gating feature
    """
    shard = 3

    @classmethod
    def setUpClass(cls):
        super(TestGatedContent, cls).setUpClass()
        cls.set_up_course()

    def setUp(self):
        super(TestGatedContent, self).setUp()
        self.setup_gating_milestone(50, 100)
        self.non_staff_user = UserFactory()
        self.staff_user = UserFactory(is_staff=True, is_superuser=True)
        self.addCleanup(set_current_request, None)
        self.request = get_mock_request(self.non_staff_user)

    @classmethod
    def set_up_course(cls):
        """
        Set up a course for testing gated content.
        """
        cls.course = CourseFactory.create(
            org='edX',
            number='EDX101',
            run='EDX101_RUN1',
            display_name='edX 101'
        )
        with modulestore().bulk_operations(cls.course.id):
            cls.course.enable_subsection_gating = True
            grading_policy = {
                "GRADER": [{
                    "type": "Homework",
                    "min_count": 3,
                    "drop_count": 0,
                    "short_label": "HW",
                    "weight": 1.0
                }]
            }
            cls.course.grading_policy = grading_policy
            cls.course.save()
            cls.store.update_item(cls.course, 0)

            # create chapter
            cls.chapter1 = ItemFactory.create(
                parent_location=cls.course.location,
                category='chapter',
                display_name='chapter 1'
            )

            # create sequentials
            cls.seq1 = ItemFactory.create(
                parent_location=cls.chapter1.location,
                category='sequential',
                display_name='gating sequential 1',
                graded=True,
                format='Homework',
            )
            cls.seq2 = ItemFactory.create(
                parent_location=cls.chapter1.location,
                category='sequential',
                display_name='gated sequential 2',
                graded=True,
                format='Homework',
            )
            cls.seq3 = ItemFactory.create(
                parent_location=cls.chapter1.location,
                category='sequential',
                display_name='sequential 3',
                graded=True,
                format='Homework',
            )

            # create problem
            cls.gating_prob1 = ItemFactory.create(
                parent_location=cls.seq1.location,
                category='problem',
                display_name='gating problem 1',
            )
            # add a discussion block to the prerequisite subsection
            # this should give us ability to test gating with blocks
            # which needs to be excluded from completion tracking
            ItemFactory.create(
                parent_location=cls.seq1.location,
                category="discussion",
                discussion_id="discussion 1",
                discussion_category="discussion category",
                discussion_target="discussion target",
            )

            cls.gated_prob2 = ItemFactory.create(
                parent_location=cls.seq2.location,
                category='problem',
                display_name='gated problem 2',
            )
            cls.prob3 = ItemFactory.create(
                parent_location=cls.seq3.location,
                category='problem',
                display_name='problem 3',
            )

    def setup_gating_milestone(self, min_score, min_completion):
        """
        Setup a gating milestone for testing.
        Gating content: seq1 (must be fulfilled before access to seq2)
        Gated content: seq2 (requires completion of seq1 before access)
        """
        gating_api.add_prerequisite(self.course.id, str(self.seq1.location))
        gating_api.set_required_content(
            self.course.id, str(self.seq2.location), str(self.seq1.location), min_score, min_completion
        )
        self.prereq_milestone = gating_api.get_gating_milestone(self.course.id, self.seq1.location, 'fulfills')

    def assert_access_to_gated_content(self, user):
        """
        Verifies access to gated content for the given user is as expected.
        """
        # clear the request cache to flush any cached access results
        RequestCache.clear_all_namespaces()

        # access to gating content (seq1) remains constant
        self.assertTrue(bool(has_access(user, 'load', self.seq1, self.course.id)))

        # access to gated content (seq2) remains constant, access is prevented in SeqModule loading
        self.assertTrue(bool(has_access(user, 'load', self.seq2, self.course.id)))

    def assert_user_has_prereq_milestone(self, user, expected_has_milestone):
        """
        Verifies whether or not the user has the prereq milestone
        """
        self.assertEquals(
            milestones_api.user_has_milestone({'id': user.id}, self.prereq_milestone),
            expected_has_milestone,
        )

    def assert_course_grade(self, user, expected_percent):
        """
        Verifies the given user's course grade is the expected percentage.
        Also verifies the user's grade information contains values for
        all problems in the course, whether or not they are currently
        gated.
        """
        course_grade = CourseGradeFactory().read(user, self.course)
        for prob in [self.gating_prob1, self.gated_prob2, self.prob3]:
            self.assertIn(prob.location, course_grade.problem_scores)

        self.assertEquals(course_grade.percent, expected_percent)

    def test_gated_for_nonstaff(self):
        self.assert_user_has_prereq_milestone(self.non_staff_user, expected_has_milestone=False)
        self.assert_access_to_gated_content(self.non_staff_user)

    def test_not_gated_for_staff(self):
        self.assert_user_has_prereq_milestone(self.staff_user, expected_has_milestone=False)
        self.assert_access_to_gated_content(self.staff_user)

    def test_gated_content_always_in_grades(self):
        with completion_waffle.waffle().override(completion_waffle.ENABLE_COMPLETION_TRACKING, True):
            # start with a grade from a non-gated subsection
            answer_problem(self.course, self.request, self.prob3, 10, 10)

            # verify gated status and overall course grade percentage
            self.assert_user_has_prereq_milestone(self.non_staff_user, expected_has_milestone=False)
            self.assert_access_to_gated_content(self.non_staff_user)
            self.assert_course_grade(self.non_staff_user, .33)

            # fulfill the gated requirements
            answer_problem(self.course, self.request, self.gating_prob1, 10, 10)

            # verify gated status and overall course grade percentage
            self.assert_user_has_prereq_milestone(self.non_staff_user, expected_has_milestone=True)
            self.assert_access_to_gated_content(self.non_staff_user)
            self.assert_course_grade(self.non_staff_user, .67)

    @ddt.data((1, 1, True), (1, 2, True), (1, 3, False), (0, 1, False))
    @ddt.unpack
    def test_ungating_when_fulfilled(self, earned, max_possible, result):
        self.assert_user_has_prereq_milestone(self.non_staff_user, expected_has_milestone=False)
        self.assert_access_to_gated_content(self.non_staff_user)
        with completion_waffle.waffle().override(completion_waffle.ENABLE_COMPLETION_TRACKING, True):
            answer_problem(self.course, self.request, self.gating_prob1, earned, max_possible)

            self.assert_user_has_prereq_milestone(self.non_staff_user, expected_has_milestone=result)
            self.assert_access_to_gated_content(self.non_staff_user)
