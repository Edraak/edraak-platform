"""
URLs for edraak marketing email.
"""
from django.conf.urls import url
from edraak_marketing_email import views


urlpatterns = [
    url(r"^marketing_email/unsubscribe$", views.UnsubscribeUserAPIView.as_view(), name="unsubscribe"),
    url(r"^marketing_email/subscribe$", views.SubscribeUserAPIView.as_view(), name="subscribe"),
]
