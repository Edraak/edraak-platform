from django.conf import settings
from django.conf.urls import url

from lms.djangoapps.edraak_certificates import views

urlpatterns = [
       url(
           r'issue/{}$'.format(settings.COURSE_ID_PATTERN),
           views.issue,
           name='edraak_certificates_issue'
       ),
       url(
           r'check/{}$'.format(settings.COURSE_ID_PATTERN),
           views.check_status,
           name='edraak_certificates_check_status'
       ),
       url(
           r'download/{}$'.format(settings.COURSE_ID_PATTERN),
           views.download,
           name='edraak_certificates_download'
       )
]
