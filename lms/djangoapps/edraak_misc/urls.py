from django.conf import settings
from django.conf.urls import url

from edraak_misc.views import check_student_grades, course_complete_status


urlpatterns = [
    url(
        r'^{course_id_pattern}/check_student_grades$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN
        ),
        check_student_grades,
        name='check_student_grades'
    ),
    url(
        r'^{course_id_pattern}/course_complete_status$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN
        ),
        course_complete_status,
        name='course_complete_status'
    ),
]
