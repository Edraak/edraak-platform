from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from edraak_marketing_email.helpers import (
    subscribe_to_marketing_emails,
    unsubscribe_from_marketing_emails
)


class UnsubscribeUserAPIView(APIView):
    """
    Unsubscribe user from marketing emails
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        user = get_object_or_404(User, email=email)
        unsubscribe_from_marketing_emails(user)

        return Response({'msg': 'user unsubscribed from marketing emails successfully'}, status=status.HTTP_201_CREATED)


class SubscribeUserAPIView(APIView):
    """
    Subscribe user to marketing emails
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        user = get_object_or_404(User, email=email)

        subscribe_to_marketing_emails(user)
        return Response({'msg': 'user subscribed to marketing emails successfully'}, status=status.HTTP_201_CREATED)

