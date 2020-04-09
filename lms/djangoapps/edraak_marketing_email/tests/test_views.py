from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from student.tests.factories import UserFactory
from edraak_marketing_email.models import UnsubscribedUser
from edraak_marketing_email.helpers import (
    subscribe_to_marketing_emails,
    unsubscribe_from_marketing_emails
)


class TestUnsubscribeUserAPIView(APITestCase):
    """Tests for handling edraak marketing email unsubscription"""

    def setUp(self):
        super(TestUnsubscribeUserAPIView, self).setUp()
        self.client = self.client_class()
        self.url = reverse('edraak_marketing_email:unsubscribe')

    def test_user_unsubscribed_successfully(self, *args):  # pylint: disable=unused-argument
        user = UserFactory()

        data = {
            'email': user.email,
            'event': 'unsubscribe'
        }
        resp = self.client.post(self.url, data, format='json')

        # Expect that the request gets through successfully,
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(UnsubscribedUser.objects.count(), 1)

    def test_already_unsubscribed_user(self, *args):  # pylint: disable=unused-argument
        user = UserFactory()
        unsubscribe_from_marketing_emails(user)

        data = {
            'email': user.email,
            'event': 'unsubscribe'
        }
        resp = self.client.post(self.url, data, format='json')

        # Expect that the request gets through successfully,
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(UnsubscribedUser.objects.count(), 1)


class TestSubscribeUserAPIView(APITestCase):
    """Tests for handling edraak marketing email subscription"""

    def setUp(self):
        super(TestSubscribeUserAPIView, self).setUp()
        self.client = self.client_class()
        self.url = reverse('edraak_marketing_email:subscribe')

    def test_user_subscribed_successfully(self, *args):  # pylint: disable=unused-argument
        user = UserFactory()

        data = {
            'email': user.email
        }
        resp = self.client.post(self.url, data, format='json')

        # Expect that the request gets through successfully,
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(UnsubscribedUser.objects.count(), 0)

    def test_already_subscribed_user(self, *args):  # pylint: disable=unused-argument
        user = UserFactory()
        subscribe_to_marketing_emails(user)

        data = {
            'email': user.email
        }
        resp = self.client.post(self.url, data, format='json')

        # Expect that the request gets through successfully,
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(UnsubscribedUser.objects.count(), 0)
