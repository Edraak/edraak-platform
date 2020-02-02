"""
Mixins for the University ID django app.
"""

from django.shortcuts import Http404

from opaque_keys.edx.locator import CourseLocator
from courseware.courses import get_course_with_access
from courseware.access import has_access


class ContextMixin(object):
    """
    A mixin that loads the course in the context data and provide a helper to check for staff access.
    """

    kwargs = {}
    request = None

    def get_course_key(self):
        """
        Get the CourseLocator object from the URL course id param.
        """
        return CourseLocator.from_string(self.kwargs['course_id'])

    def get_course(self):
        """
        Gets the Course object.
        """
        course_key = self.get_course_key()
        return get_course_with_access(self.request.user, 'load', course_key)

    def require_staff_access(self):
        """
        Raises a 404 exception if the user does not have staff access.
        """
        course = self.get_course()
        if not has_access(self.request.user, 'staff', course):
            raise Http404('Course does not exists, or user does not have permission.')

    def is_staff(self):
        return has_access(self.request.user, 'staff', self.get_course())

    def get_context_data(self, **kwargs):
        """
        Add the course to the context data.
        """
        data = super(ContextMixin, self).get_context_data(**kwargs)
        data['course'] = self.get_course()
        data['is_staff'] = self.is_staff()
        data['course_key'] = self.get_course_key()
        return data
