"""
This module contains tests for programs-related signals and signal handlers.
"""

from django.test import TestCase
import mock

from opaque_keys.edx.keys import CourseKey
from student.tests.factories import UserFactory

from openedx.core.djangoapps.signals.signals import COURSE_CERT_AWARDED, COURSE_CERT_CHANGED
from openedx.core.djangoapps.programs.signals import handle_course_cert_awarded, handle_course_cert_changed
from openedx.core.djangoapps.site_configuration.tests.factories import SiteConfigurationFactory
from openedx.core.djangolib.testing.utils import skip_unless_lms

TEST_USERNAME = 'test-user'
TEST_COURSE_KEY = CourseKey.from_string('course-v1:edX+test_course+1')


# The credentials app isn't installed for the CMS.
@skip_unless_lms
@mock.patch('openedx.core.djangoapps.programs.tasks.v1.tasks.award_program_certificates.delay')
@mock.patch(
    'openedx.core.djangoapps.credentials.models.CredentialsApiConfig.is_learner_issuance_enabled',
    new_callable=mock.PropertyMock,
    return_value=False,
)
class CertAwardedReceiverTest(TestCase):
    """
    Tests for the `handle_course_cert_awarded` signal handler function.
    """
    shard = 2

    @property
    def signal_kwargs(self):
        """
        DRY helper.
        """
        return dict(
            sender=self.__class__,
            user=UserFactory.create(username=TEST_USERNAME),
            course_key=TEST_COURSE_KEY,
            mode='test-mode',
            status='test-status',
        )

    def test_signal_received(self, mock_is_learner_issuance_enabled, mock_task):  # pylint: disable=unused-argument
        """
        Ensures the receiver function is invoked when COURSE_CERT_AWARDED is
        sent.

        Suboptimal: because we cannot mock the receiver function itself (due
        to the way django signals work), we mock a configuration call that is
        known to take place inside the function.
        """
        COURSE_CERT_AWARDED.send(**self.signal_kwargs)
        self.assertEqual(mock_is_learner_issuance_enabled.call_count, 1)

    def test_programs_disabled(self, mock_is_learner_issuance_enabled, mock_task):
        """
        Ensures that the receiver function does nothing when the credentials API
        configuration is not enabled.
        """
        handle_course_cert_awarded(**self.signal_kwargs)
        self.assertEqual(mock_is_learner_issuance_enabled.call_count, 1)
        self.assertEqual(mock_task.call_count, 0)

    def test_programs_enabled(self, mock_is_learner_issuance_enabled, mock_task):
        """
        Ensures that the receiver function invokes the expected celery task
        when the credentials API configuration is enabled.
        """
        mock_is_learner_issuance_enabled.return_value = True

        handle_course_cert_awarded(**self.signal_kwargs)

        self.assertEqual(mock_is_learner_issuance_enabled.call_count, 1)
        self.assertEqual(mock_task.call_count, 1)
        self.assertEqual(mock_task.call_args[0], (TEST_USERNAME,))


# The credentials app isn't installed for the CMS.
@skip_unless_lms
@mock.patch('openedx.core.djangoapps.programs.tasks.v1.tasks.award_course_certificate.delay')
@mock.patch(
    'openedx.core.djangoapps.credentials.models.CredentialsApiConfig.is_learner_issuance_enabled',
    new_callable=mock.PropertyMock,
    return_value=False,
)
class CertChangedReceiverTest(TestCase):
    """
    Tests for the `handle_course_cert_changed` signal handler function.
    """
    shard = 2

    def setUp(self):
        super(CertChangedReceiverTest, self).setUp()
        self.user = UserFactory.create(username=TEST_USERNAME)

    @property
    def signal_kwargs(self):
        """
        DRY helper.
        """
        return dict(
            sender=self.__class__,
            user=self.user,
            course_key=TEST_COURSE_KEY,
            mode='test-mode',
            status='test-status',
        )

    def test_signal_received(self, mock_is_learner_issuance_enabled, mock_task):  # pylint: disable=unused-argument
        """
        Ensures the receiver function is invoked when COURSE_CERT_CHANGED is
        sent.

        Suboptimal: because we cannot mock the receiver function itself (due
        to the way django signals work), we mock a configuration call that is
        known to take place inside the function.
        """
        COURSE_CERT_CHANGED.send(**self.signal_kwargs)
        self.assertEqual(mock_is_learner_issuance_enabled.call_count, 2)

    def test_credentials_disabled(self, mock_is_learner_issuance_enabled, mock_task):
        """
        Ensures that the receiver function does nothing when the credentials API
        configuration is not enabled.
        """
        handle_course_cert_changed(**self.signal_kwargs)
        self.assertEqual(mock_is_learner_issuance_enabled.call_count, 1)
        self.assertEqual(mock_task.call_count, 0)

    def test_credentials_enabled(self, mock_is_learner_issuance_enabled, mock_task):
        """
        Ensures that the receiver function invokes the expected celery task
        when the credentials API configuration is enabled.
        """
        mock_is_learner_issuance_enabled.return_value = True

        handle_course_cert_changed(**self.signal_kwargs)

        self.assertEqual(mock_is_learner_issuance_enabled.call_count, 1)
        self.assertEqual(mock_task.call_count, 1)
        self.assertEqual(mock_task.call_args[0], (TEST_USERNAME, str(TEST_COURSE_KEY)))

    def test_records_enabled(self, mock_is_learner_issuance_enabled, mock_task):
        mock_is_learner_issuance_enabled.return_value = True

        site_config = SiteConfigurationFactory.create(
            values={'course_org_filter': ['edX']},
        )

        # Correctly sent
        handle_course_cert_changed(**self.signal_kwargs)
        self.assertTrue(mock_task.called)
        mock_task.reset_mock()

        # Correctly not sent
        site_config.values['ENABLE_LEARNER_RECORDS'] = False
        site_config.save()
        handle_course_cert_changed(**self.signal_kwargs)
        self.assertFalse(mock_task.called)
