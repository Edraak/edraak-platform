"""
Edraak ForUs module urls
"""
from django.conf.urls import patterns, url
from edraak_forus.views import RegistrationApiView, AuthView, MessageView


urlpatterns = patterns(
    '',
    url(r'^auth$', AuthView.as_view(), name='auth'),
    url('^api/registration', RegistrationApiView.as_view(), name='reg_api'),
    url('^message$', MessageView.as_view(), name='message'),
)
