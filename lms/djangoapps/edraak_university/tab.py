"""
Courseware tab classe.
"""
from django.utils.translation import ugettext_noop
from django.conf import settings

from courseware.tabs import EnrolledTab
from edraak_university.helpers import is_feature_enabled


class UniversityIDTab(EnrolledTab):
    """
    A course tab that links to the "University ID" view.
    """

    type = 'university_id'
    title = ugettext_noop('University ID')
    priority = None
    view_name = 'edraak_university:id'
    is_default = True

    @classmethod
    def is_enabled(cls, course, user=None):
        """
        Decides whether to show the course tab or not, based on course and platform settings.
        """
        if not is_feature_enabled() or not course.enable_university_id:
            return False

        if super(UniversityIDTab, cls).is_enabled(course, user):
            return True

        if settings.ROOT_URLCONF == 'cms.urls':
            # The platform don't provide a user when the tab is show on CMS
            # So this ensures that the tab shows up in CMS
            return True

        return False
