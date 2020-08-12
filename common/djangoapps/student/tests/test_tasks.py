"""
Tests for the Sending activation email celery tasks
"""

import mock
from boto.exception import NoAuthHandlerFound
from django.conf import settings
from django.test import TestCase

from lms.djangoapps.courseware.tests.factories import UserFactory
from student.tasks import send_activation_email


class SendActivationEmailTestCase(TestCase):
    """
    Test for send activation email to user
    """
    def setUp(self):
        """ Setup components used by each test."""
        super(SendActivationEmailTestCase, self).setUp()
        self.student = UserFactory()

    @mock.patch('time.sleep', mock.Mock(return_value=None))
    @mock.patch('student.tasks.log')
    @mock.patch('django.core.mail.send_mail', mock.Mock(side_effect=NoAuthHandlerFound))
    def test_send_email(self, mock_log):
        """
        Tests retries when the activation email doesn't send
        """
        from_address = 'task_testing@example.com'
        email_max_attempts = settings.RETRY_ACTIVATION_EMAIL_MAX_ATTEMPTS

        # pylint: disable=no-member
        send_activation_email.delay('Task_test', 'Task_test_message', from_address, self.student.email)

        # Asserts sending email retry logging.
        for attempt in range(email_max_attempts):
            mock_log.info.assert_any_call(
                'Retrying sending email to user {dest_addr}, attempt # {attempt} of {max_attempts}'.format(
                    dest_addr=self.student.email,
                    attempt=attempt,
                    max_attempts=email_max_attempts
                ))
        self.assertEquals(mock_log.info.call_count, 6)

        # Asserts that the error was logged on crossing max retry attempts.
        mock_log.error.assert_called_with(
            'Unable to send activation email to user from "%s" to "%s"',
            from_address,
            self.student.email,
            exc_info=True
        )
        self.assertEquals(mock_log.error.call_count, 1)
