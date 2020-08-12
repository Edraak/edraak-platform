"""
OAuth2 wrapper urls
"""

from django.conf import settings
from django.conf.urls import url
from django.views.decorators.csrf import csrf_exempt

from . import views

urlpatterns = [
    url(r'^authorize/?$', csrf_exempt(views.AuthorizationView.as_view()), name='authorize'),
    url(r'^access_token/?$', csrf_exempt(views.AccessTokenView.as_view()), name='access_token'),
    url(r'^revoke_token/?$', csrf_exempt(views.RevokeTokenView.as_view()), name='revoke_token'),
]

if settings.FEATURES.get('ENABLE_THIRD_PARTY_AUTH'):
    urlpatterns += [
        url(
            r'^exchange_access_token/(?P<backend>[^/]+)/$',
            csrf_exempt(views.AccessTokenExchangeView.as_view()),
            name='exchange_access_token',
        ),
    ]
