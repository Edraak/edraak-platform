from django.conf.urls import patterns, url
from edraak_dummy.views import SetCSRFDummyView

urlpatterns = patterns('',  # nopep8
    url('^edraak_set/csrf', SetCSRFDummyView.as_view(), name='edraak_setcsrf'),
)
