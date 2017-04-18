"""
University ID views.
"""

from django.core.urlresolvers import reverse
from django.views import generic
from django.shortcuts import redirect

from openedx.core.djangoapps.user_api.accounts.api import update_account_settings

from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required

from util.views import ensure_valid_course_key

from courseware.access import has_access
from student.models import UserProfile

from edraak_university.forms import UniversityIDForm
from edraak_university.models import UniversityID
from edraak_university.helpers import get_university_id, has_valid_university_id
from edraak_university.mixins import CourseContextMixin


class UniversityIDView(CourseContextMixin, generic.FormView):
    """
    The student University ID form view.
    """

    template_name = 'edraak_university/university_id.html'
    form_class = UniversityIDForm

    def get(self, *args, **kwargs):
        """
        Overrides `get` method to redirect course staff to the instructor list view.

        This would have been done better if the course tab URL property can tell which user it is providing the
        URL to.
        """

        course = self.get_course()

        if has_access(self.request.user, 'staff', course):
            return redirect('edraak_university:id_list', course_id=course.id)
        else:
            return super(UniversityIDView, self).get(*args, **kwargs)

    def get_form_kwargs(self):
        """
        Put university in the form kwargs.

        Note to developers: Note sure why this is here, it's an old code.
        """

        kwargs = super(UniversityIDView, self).get_form_kwargs()
        instance = get_university_id(self.request.user, self.kwargs['course_id'])
        if instance:
            kwargs['instance'] = instance

        return kwargs

    def get_initial(self):
        """
        Initialize the full name from the profile.
        """
        profile = UserProfile.objects.get(user=self.request.user)

        return {
            'full_name': profile.name,
        }

    def form_valid(self, form):
        """
        A hook to set the course_key and to update the profile.name.
        """

        instance = form.save(commit=False)
        instance.user = self.request.user
        instance.course_key = self.get_course_key()
        instance.save()

        update_account_settings(self.request.user, {
            'name': form.cleaned_data['full_name'],
        })

        return super(UniversityIDView, self).form_valid(form)

    def get_success_url(self):
        return reverse('edraak_university:id_success', kwargs={
            'course_id': self.kwargs['course_id'],
        })

    def get_context_data(self, **kwargs):
        data = super(UniversityIDView, self).get_context_data(**kwargs)
        data.update({
            'form': self.get_form(),
            'has_valid_information': has_valid_university_id(self.request.user, self.kwargs['course_id']),
        })

        return data

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures login and a valid course key.
        """
        return super(UniversityIDView, self).dispatch(*args, **kwargs)


class UniversityIDSuccessView(CourseContextMixin, generic.TemplateView):
    """
    Just a plain student university ID success view with a link to the course content.
    """

    template_name = 'edraak_university/university_id_success.html'

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures login and a valid course key.
        """
        return super(UniversityIDSuccessView, self).dispatch(*args, **kwargs)


class UniversityIDListView(CourseContextMixin, generic.ListView):
    """
    A list of IDs for instructors to review and modify.
    """
    model = UniversityID
    template_name = 'edraak_university/instructor/list.html'

    def get_queryset(self):
        return UniversityID.get_marked_university_ids(course_key=self.get_course_key())

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures only staff has access to the module..
        """
        self.require_staff_access()
        return super(UniversityIDListView, self).dispatch(*args, **kwargs)


class UniversityIDUpdateView(CourseContextMixin, generic.UpdateView):
    """
    Instructor update view for the student ID.
    """
    model = UniversityID
    template_name = 'edraak_university/instructor/update.html'

    # The email and full_name fields are written directly in the `update.html` file.
    fields = ('university_id', 'section_number',)

    def get_success_url(self):
        return reverse('edraak_university:id_list', kwargs={
            'course_id': self.get_course_key(),
        })

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures only staff has access to the module..
        """
        self.require_staff_access()
        return super(UniversityIDUpdateView, self).dispatch(*args, **kwargs)


class UniversityIDDeleteView(CourseContextMixin, generic.DeleteView):
    """
    Instructor delete view for the student ID.
    """
    model = UniversityID
    template_name = 'edraak_university/instructor/delete.html'

    def get_success_url(self):
        return reverse('edraak_university:id_list', kwargs={
            'course_id': self.get_course_key(),
        })

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures only staff has access to the module..
        """
        self.require_staff_access()
        return super(UniversityIDDeleteView, self).dispatch(*args, **kwargs)
