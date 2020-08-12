import json
import re

from course_modes.models import CourseMode
from course_modes.tests.factories import CourseModeFactory
from django_comment_common.models import CourseDiscussionSettings
from django_comment_common.utils import set_course_discussion_settings
from lms.djangoapps.teams.tests.factories import CourseTeamFactory


class GroupIdAssertionMixin(object):
    def _data_or_params_cs_request(self, mock_request):
        """
        Returns the data or params dict that `mock_request` was called with.
        """
        call = [call for call in mock_request.call_args_list if call[0][1].endswith(self.cs_endpoint)][0]
        if call[0][0] == "get":
            return call[1]["params"]
        elif call[0][0] == "post":
            return call[1]["data"]

    def _assert_comments_service_called_with_group_id(self, mock_request, group_id):
        self.assertTrue(mock_request.called)
        self.assertEqual(self._data_or_params_cs_request(mock_request)["group_id"], group_id)

    def _assert_comments_service_called_without_group_id(self, mock_request):
        self.assertTrue(mock_request.called)
        self.assertNotIn("group_id", self._data_or_params_cs_request(mock_request))

    def _assert_html_response_contains_group_info(self, response):
        group_info = {"group_id": None, "group_name": None}
        match = re.search(r'"group_id": (\d*),', response.content)
        if match and match.group(1) != '':
            group_info["group_id"] = int(match.group(1))
        match = re.search(r'"group_name": "(\w*)",', response.content)
        if match:
            group_info["group_name"] = match.group(1)
        self._assert_thread_contains_group_info(group_info)

    def _assert_json_response_contains_group_info(self, response, extract_thread=None):
        """
        :param extract_thread: a function which accepts a dictionary (complete
            json response payload) and returns another dictionary (first
            occurrence of a thread model within that payload).  if None is
            passed, the identity function is assumed.
        """
        payload = json.loads(response.content)
        thread = extract_thread(payload) if extract_thread else payload
        self._assert_thread_contains_group_info(thread)

    def _assert_thread_contains_group_info(self, thread):
        self.assertEqual(thread['group_id'], self.student_cohort.id)
        self.assertEqual(thread['group_name'], self.student_cohort.name)


class CohortedTopicGroupIdTestMixin(GroupIdAssertionMixin):
    """
    Provides test cases to verify that views pass the correct `group_id` to
    the comments service when requesting content in cohorted discussions.
    """
    def call_view(self, mock_request, commentable_id, user, group_id, pass_group_id=True):
        """
        Call the view for the implementing test class, constructing a request
        from the parameters.
        """
        pass

    def test_cohorted_topic_student_without_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.student, None, pass_group_id=False)
        self._assert_comments_service_called_with_group_id(mock_request, self.student_cohort.id)

    def test_cohorted_topic_student_none_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.student, "")
        self._assert_comments_service_called_with_group_id(mock_request, self.student_cohort.id)

    def test_cohorted_topic_student_with_own_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.student, self.student_cohort.id)
        self._assert_comments_service_called_with_group_id(mock_request, self.student_cohort.id)

    def test_cohorted_topic_student_with_other_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.student, self.moderator_cohort.id)
        self._assert_comments_service_called_with_group_id(mock_request, self.student_cohort.id)

    def test_cohorted_topic_moderator_without_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.moderator, None, pass_group_id=False)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_cohorted_topic_moderator_none_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.moderator, "")
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_cohorted_topic_moderator_with_own_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.moderator, self.moderator_cohort.id)
        self._assert_comments_service_called_with_group_id(mock_request, self.moderator_cohort.id)

    def test_cohorted_topic_moderator_with_other_group_id(self, mock_request):
        self.call_view(mock_request, "cohorted_topic", self.moderator, self.student_cohort.id)
        self._assert_comments_service_called_with_group_id(mock_request, self.student_cohort.id)

    def test_cohorted_topic_moderator_with_invalid_group_id(self, mock_request):
        invalid_id = self.student_cohort.id + self.moderator_cohort.id
        response = self.call_view(mock_request, "cohorted_topic", self.moderator, invalid_id)
        self.assertEqual(response.status_code, 500)

    def test_cohorted_topic_enrollment_track_invalid_group_id(self, mock_request):
        CourseModeFactory.create(course_id=self.course.id, mode_slug=CourseMode.AUDIT)
        CourseModeFactory.create(course_id=self.course.id, mode_slug=CourseMode.VERIFIED)
        set_course_discussion_settings(
            course_key=self.course.id,
            divided_discussions=['cohorted_topic'],
            division_scheme=CourseDiscussionSettings.ENROLLMENT_TRACK,
            always_divide_inline_discussions=True,
        )

        invalid_id = -1000
        response = self.call_view(mock_request, "cohorted_topic", self.moderator, invalid_id)
        self.assertEqual(response.status_code, 500)


class NonCohortedTopicGroupIdTestMixin(GroupIdAssertionMixin):
    """
    Provides test cases to verify that views pass the correct `group_id` to
    the comments service when requesting content in non-cohorted discussions.
    """
    def call_view(self, mock_request, commentable_id, user, group_id, pass_group_id=True):
        """
        Call the view for the implementing test class, constructing a request
        from the parameters.
        """
        pass

    def test_non_cohorted_topic_student_without_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.student, None, pass_group_id=False)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_student_none_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.student, None)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_student_with_own_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.student, self.student_cohort.id)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_student_with_other_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.student, self.moderator_cohort.id)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_moderator_without_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.moderator, None, pass_group_id=False)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_moderator_none_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.moderator, None)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_moderator_with_own_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.moderator, self.moderator_cohort.id)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_moderator_with_other_group_id(self, mock_request):
        self.call_view(mock_request, "non_cohorted_topic", self.moderator, self.student_cohort.id)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_non_cohorted_topic_moderator_with_invalid_group_id(self, mock_request):
        invalid_id = self.student_cohort.id + self.moderator_cohort.id
        self.call_view(mock_request, "non_cohorted_topic", self.moderator, invalid_id)
        self._assert_comments_service_called_without_group_id(mock_request)

    def test_team_discussion_id_not_cohorted(self, mock_request):
        team = CourseTeamFactory(course_id=self.course.id)

        team.add_user(self.student)
        self.call_view(mock_request, team.discussion_topic_id, self.student, None)

        self._assert_comments_service_called_without_group_id(mock_request)
