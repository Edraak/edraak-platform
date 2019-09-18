from django.conf.urls import url
from edraak_dummy.views import SetCSRFDummyView

urlpatterns = [
    url('^edraak_set/csrf', SetCSRFDummyView.as_view(), name='edraak_setcsrf')
]
