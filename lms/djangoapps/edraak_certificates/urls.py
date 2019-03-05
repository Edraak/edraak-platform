from django.conf import settings
from django.conf.urls import url

from edraak_certificates import views

urlpatterns = [
    url(
        r'^{course_id_pattern}/issue$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        views.issue,
        name='issue',
    ),
    url(
        r'^{course_id_pattern}/preview$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        views.preview,
        name='preview',
    ),
    url(
        r'^{course_id_pattern}/download_pdf$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        views.download_pdf,
        name='download_pdf',
    ),
    url(
        r'^{course_id_pattern}/preview_png$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        views.preview_png,
        name='preview_png',
    ),
]
