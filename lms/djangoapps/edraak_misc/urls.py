from django.conf import settings
from django.conf.urls import url

from edraak_misc.views import check_student_grades, student_course_complete_status


urlpatterns = [
    url(
        r'^check_student_grades/$',
        check_student_grades,
        name='edraak_check_student_grades'
    ),
    url(
        r'^course_complete_status/{}$'.format(settings.COURSE_ID_PATTERN),
        student_course_complete_status,
        name='edraak_all_courses'
    ),
]
