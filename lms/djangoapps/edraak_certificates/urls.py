from django.conf import settings
from django.conf.urls import patterns, url

urlpatterns = patterns(
    'edraak_certificates.views',
    url(
        r'^{course_id_pattern}/issue$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        view='issue',
        name='issue',
    ),
    url(
        r'^{course_id_pattern}/preview$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        view='preview',
        name='preview',
    ),
    url(
        r'^{course_id_pattern}/download_pdf$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        view='download_pdf',
        name='download_pdf',
    ),
    url(
        r'^{course_id_pattern}/preview_png$'.format(
            course_id_pattern=settings.COURSE_ID_PATTERN,
        ),
        view='preview_png',
        name='preview_png',
    ),
)
