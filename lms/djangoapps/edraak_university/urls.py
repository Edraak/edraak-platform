"""
URLs for the Edraak University ID app.
"""
from django.conf.urls import url
from django.conf import settings

from edraak_university import views


urlpatterns = [
    url(
        r'^id/{}$'.format(settings.COURSE_ID_PATTERN),
        views.UniversityIDView.as_view(),
        name='id',
    ),
    url(
        r'^id/{}/success$'.format(settings.COURSE_ID_PATTERN),
        views.UniversityIDSuccessView.as_view(),
        name='id_success',
    ),
    url(
        r'^id/{}/settings_success$'.format(settings.COURSE_ID_PATTERN),
        views.UniversityIDSettingsSuccessView.as_view(),
        name='id_settings_success',
    ),
    url(
        r'^id/{}/instructor/list$'.format(settings.COURSE_ID_PATTERN),
        views.UniversityIDStaffView.as_view(),
        name='id_staff',
    ),
    url(
        r'^id/{}/instructor/update/(?P<pk>\d+)$'.format(settings.COURSE_ID_PATTERN),
        views.UniversityIDUpdateView.as_view(),
        name='id_update',
    ),
    url(
        r'^id/{}/instructor/delete/(?P<pk>\d+)$'.format(settings.COURSE_ID_PATTERN),
        views.UniversityIDDeleteView.as_view(),
        name='id_delete',
    ),
]
