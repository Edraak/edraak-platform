from django.conf.urls import patterns, url
from edraak_forus.views import RegistrationApiView, AuthView


urlpatterns = patterns('',  # nopep8
    url(r'^v1/auth$', AuthView.as_view(), name='forus_v1_auth'),
    url('^v1/api/registration', RegistrationApiView.as_view(), name='forus_v1_reg_api'),
    url('^message', 'edraak_forus.views.message', name='forus_v1_message'),
)
