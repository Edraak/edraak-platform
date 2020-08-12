"""
Unit tests for integration of the django-user-tasks app and its REST API.
"""

from __future__ import absolute_import, print_function, unicode_literals

import logging
from uuid import uuid4

import mock
from boto.exception import NoAuthHandlerFound
from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.urls import reverse
from django.test import override_settings
from rest_framework.test import APITestCase
from user_tasks.models import UserTaskArtifact, UserTaskStatus
from user_tasks.serializers import ArtifactSerializer, StatusSerializer

from .signals import user_task_stopped


class MockLoggingHandler(logging.Handler):
    """
    Mock logging handler to help check for logging statements
    """
    def __init__(self, *args, **kwargs):
        self.reset()
        logging.Handler.__init__(self, *args, **kwargs)

    def emit(self, record):
        """
        Override to catch messages and store them messages in our internal dicts
        """
        self.messages[record.levelname.lower()].append(record.getMessage())

    def reset(self):
        """
        Clear out all messages, also called to initially populate messages dict
        """
        self.messages = {
            'debug': [],
            'info': [],
            'warning': [],
            'error': [],
            'critical': [],
        }


# Helper functions for stuff that pylint complains about without disable comments
def _context(response):
    """
    Get a context dictionary for a serializer appropriate for the given response.
    """
    return {'request': response.wsgi_request}


def _data(response):
    """
    Get the serialized data dictionary from the given REST API test response.
    """
    return response.data


@override_settings(BROKER_URL='memory://localhost/')
class TestUserTasks(APITestCase):
    """
    Tests of the django-user-tasks REST API endpoints.

    Detailed tests of the default authorization rules are in the django-user-tasks code.
    These tests just verify that the API is exposed and functioning.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('test_user', 'test@example.com', 'password')
        cls.status = UserTaskStatus.objects.create(
            user=cls.user, task_id=str(uuid4()), task_class='test_rest_api.sample_task', name='SampleTask 2',
            total_steps=5)
        cls.artifact = UserTaskArtifact.objects.create(status=cls.status, text='Lorem ipsum')

    def setUp(self):
        super(TestUserTasks, self).setUp()
        self.status.refresh_from_db()
        self.client.force_authenticate(self.user)  # pylint: disable=no-member

    def test_artifact_detail(self):
        """
        Users should be able to access artifacts for tasks they triggered.
        """
        response = self.client.get(reverse('usertaskartifact-detail', args=[self.artifact.uuid]))
        assert response.status_code == 200
        serializer = ArtifactSerializer(self.artifact, context=_context(response))
        assert _data(response) == serializer.data

    def test_artifact_list(self):
        """
        Users should be able to access a list of their tasks' artifacts.
        """
        response = self.client.get(reverse('usertaskartifact-list'))
        assert response.status_code == 200
        serializer = ArtifactSerializer(self.artifact, context=_context(response))
        assert _data(response)['results'] == [serializer.data]

    def test_status_cancel(self):
        """
        Users should be able to cancel tasks they no longer wish to complete.
        """
        response = self.client.post(reverse('usertaskstatus-cancel', args=[self.status.uuid]))
        assert response.status_code == 200
        self.status.refresh_from_db()
        assert self.status.state == UserTaskStatus.CANCELED

    def test_status_delete(self):
        """
        Users should be able to delete their own task status records when they're done with them.
        """
        response = self.client.delete(reverse('usertaskstatus-detail', args=[self.status.uuid]))
        assert response.status_code == 204
        assert not UserTaskStatus.objects.filter(pk=self.status.id).exists()

    def test_status_detail(self):
        """
        Users should be able to access status records for tasks they triggered.
        """
        response = self.client.get(reverse('usertaskstatus-detail', args=[self.status.uuid]))
        assert response.status_code == 200
        serializer = StatusSerializer(self.status, context=_context(response))
        assert _data(response) == serializer.data

    def test_status_list(self):
        """
        Users should be able to access a list of their tasks' status records.
        """
        response = self.client.get(reverse('usertaskstatus-list'))
        assert response.status_code == 200
        serializer = StatusSerializer([self.status], context=_context(response), many=True)
        assert _data(response)['results'] == serializer.data


@override_settings(BROKER_URL='memory://localhost/')
class TestUserTaskStopped(APITestCase):
    """
    Tests of the django-user-tasks signal handling and email integration.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('test_user', 'test@example.com', 'password')
        cls.status = UserTaskStatus.objects.create(
            user=cls.user, task_id=str(uuid4()), task_class='test_rest_api.sample_task', name='SampleTask 2',
            total_steps=5)

    def setUp(self):
        super(TestUserTaskStopped, self).setUp()
        self.status.refresh_from_db()
        self.client.force_authenticate(self.user)  # pylint: disable=no-member

    def test_email_sent_with_site(self):
        """
        Check the signal receiver and email sending.
        """
        UserTaskArtifact.objects.create(
            status=self.status, name='BASE_URL', url='https://test.edx.org/'
        )
        user_task_stopped.send(sender=UserTaskStatus, status=self.status)

        subject = "{platform_name} {studio_name}: Task Status Update".format(
            platform_name=settings.PLATFORM_NAME, studio_name=settings.STUDIO_NAME
        )
        body_fragments = [
            "Your {task_name} task has completed with the status".format(task_name=self.status.name.lower()),
            "https://test.edx.org/",
            reverse('usertaskstatus-detail', args=[self.status.uuid])
        ]

        self.assertEqual(len(mail.outbox), 1)

        msg = mail.outbox[0]

        self.assertEqual(msg.subject, subject)
        for fragment in body_fragments:
            self.assertIn(fragment, msg.body)

    def test_email_not_sent_for_child(self):
        """
        No email should be send for child tasks in chords, chains, etc.
        """
        child_status = UserTaskStatus.objects.create(
            user=self.user, task_id=str(uuid4()), task_class='test_rest_api.sample_task', name='SampleTask 2',
            total_steps=5, parent=self.status)
        user_task_stopped.send(sender=UserTaskStatus, status=child_status)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_sent_without_site(self):
        """
        Make sure we send a generic email if the BASE_URL artifact doesn't exist
        """
        user_task_stopped.send(sender=UserTaskStatus, status=self.status)

        subject = "{platform_name} {studio_name}: Task Status Update".format(
            platform_name=settings.PLATFORM_NAME, studio_name=settings.STUDIO_NAME
        )
        fragments = [
            "Your {task_name} task has completed with the status".format(task_name=self.status.name.lower()),
            "Sign in to view the details of your task or download any files created."
        ]

        self.assertEqual(len(mail.outbox), 1)

        msg = mail.outbox[0]
        self.assertEqual(msg.subject, subject)

        for fragment in fragments:
            self.assertIn(fragment, msg.body)

    def test_email_retries(self):
        """
        Make sure we can succeed on retries
        """
        with mock.patch('django.core.mail.send_mail') as mock_exception:
            mock_exception.side_effect = NoAuthHandlerFound()

            with mock.patch('cms_user_tasks.tasks.send_task_complete_email.retry') as mock_retry:
                user_task_stopped.send(sender=UserTaskStatus, status=self.status)
                self.assertTrue(mock_retry.called)

    def test_queue_email_failure(self):
        logger = logging.getLogger("cms_user_tasks.signals")
        hdlr = MockLoggingHandler(level="DEBUG")
        logger.addHandler(hdlr)

        with mock.patch('cms_user_tasks.tasks.send_task_complete_email.delay') as mock_delay:
            mock_delay.side_effect = NoAuthHandlerFound()
            user_task_stopped.send(sender=UserTaskStatus, status=self.status)
            self.assertTrue(mock_delay.called)
            self.assertEqual(hdlr.messages['error'][0], u'Unable to queue send_task_complete_email')
