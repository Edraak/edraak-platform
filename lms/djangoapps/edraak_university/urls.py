"""
URLs for the Edraak University ID app.
"""
from django.conf.urls import patterns, url
from django.conf import settings

from edraak_university import views


urlpatterns = patterns(
    '',
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
        r'^id/{}/instructor/list$'.format(settings.COURSE_ID_PATTERN),
        views.UniversityIDListView.as_view(),
        name='id_list',
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
)
