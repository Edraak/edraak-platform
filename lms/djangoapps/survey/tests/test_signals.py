"""
Test signal handlers for the survey app
"""

from openedx.core.djangoapps.user_api.accounts.tests.retirement_helpers import fake_completed_retirement
from student.tests.factories import UserFactory
from survey.models import SurveyAnswer
from survey.tests.factories import SurveyAnswerFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from lms.djangoapps.survey.signals import _listen_for_lms_retire


class SurveyRetireSignalTests(ModuleStoreTestCase):
    """
    Test the _listen_for_lms_retire signal
    """
    shard = 4

    def test_success_answers_exist(self):
        """
        Basic success path for users that have answers in the table
        """
        answer = SurveyAnswerFactory(field_value="test value")

        _listen_for_lms_retire(sender=self.__class__, user=answer.user)

        # All values for this user should now be empty string
        self.assertFalse(SurveyAnswer.objects.filter(user=answer.user).exclude(field_value='').exists())

    def test_success_no_answers(self):
        """
        Basic success path for users who have no answers, should simply not error
        """
        user = UserFactory()
        _listen_for_lms_retire(sender=self.__class__, user=user)

    def test_idempotent(self):
        """
        Tests that re-running a retirement multiple times does not throw an error
        """
        answer = SurveyAnswerFactory(field_value="test value")

        # Run twice to make sure no errors are raised
        _listen_for_lms_retire(sender=self.__class__, user=answer.user)
        fake_completed_retirement(answer.user)
        _listen_for_lms_retire(sender=self.__class__, user=answer.user)

        # All values for this user should still be here and just be an empty string
        self.assertFalse(SurveyAnswer.objects.filter(user=answer.user).exclude(field_value='').exists())
