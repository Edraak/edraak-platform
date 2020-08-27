"""
University ID views.
"""
from django.core.urlresolvers import reverse
from django.db import transaction
from django.views import generic
from django.shortcuts import redirect
from django.conf import settings
from openedx.core.djangoapps.course_groups.models import CourseUserGroup

from edxmako.shortcuts import marketing_link
from openedx.core.djangoapps.course_groups.cohorts import add_user_to_cohort, get_cohort_id, get_cohort_by_id
from openedx.core.djangoapps.user_api.accounts.api import update_account_settings

from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required

from util.date_utils import strftime_localized
from util.views import ensure_valid_course_key

from courseware.views.views import CourseTabView
from student.models import UserProfile

from edraak_university.forms import UniversityIDStudentForm
from edraak_university import forms
from edraak_university.models import UniversityID
from edraak_university.helpers import (
    get_university_id,
    has_valid_university_id,
    show_enroll_banner,
    is_student_form_disabled,
    get_university_settings,
)
from edraak_university.mixins import ContextMixin


class UniversityIDView(ContextMixin, generic.FormView):
    """
    The student University ID form view.
    """

    template_name = 'edraak_university/university_id.html'
    form_class = UniversityIDStudentForm

    def get(self, *args, **kwargs):
        """
        Overrides `get` method to redirect course staff to the instructor list view.

        This would have been done better if the course tab URL property can tell which user it is providing the
        URL to.
        """

        course = self.get_course()

        if not self.get_course().enable_university_id:
            return redirect('course_root', unicode(course.id))

        if self.is_staff():
            return redirect('edraak_university:id_staff', course_id=course.id)

        CourseTabView.register_user_access_warning_messages(self.request, course)

        return super(UniversityIDView, self).get(*args, **kwargs)

    def get_form_kwargs(self):
        """
        Put university in the form kwargs.

        Note to developers: Note sure why this is here, it's an old code.
        """

        kwargs = super(UniversityIDView, self).get_form_kwargs()
        kwargs['course_key'] = self.get_course_key()
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
            'cohort': get_cohort_id(user=self.request.user, course_key=self.get_course_key()),
            'full_name': profile.name,
        }

    def form_valid(self, form):
        """
        A hook to set the course_key, set the cohort and the profile.name.
        """
        if is_student_form_disabled(self.request.user, self.get_course_key()):
            # Don't allow saving the disabled form
            return self.form_invalid(form)

        instance = form.save(commit=False)
        instance.user = self.request.user
        instance.course_key = self.get_course_key()
        instance.save()

        update_account_settings(self.request.user, {
            'name': form.cleaned_data['full_name'],
        })

        cohort = CourseUserGroup.objects.get(pk=form.cleaned_data['cohort'])
        instance.set_cohort(cohort)

        return super(UniversityIDView, self).form_valid(form)

    def get_success_url(self):
        return reverse('edraak_university:id_success', kwargs={
            'course_id': self.kwargs['course_id'],
        })

    def show_enroll_banner(self):
        return show_enroll_banner(self.request.user, self.get_course_key())

    def get_context_data(self, **kwargs):
        data = super(UniversityIDView, self).get_context_data(**kwargs)

        registration_end_date = None
        terms_and_conditions = None

        university_settings = get_university_settings(self.get_course_key())
        if university_settings:
            terms_and_conditions = university_settings.terms_and_conditions
            final_date = university_settings.registration_end_date
            date = strftime_localized(final_date, format='SHORT_DATE')
            registration_end_date = date.replace('"', '')

        if settings.FEATURES.get('ENABLE_MKTG_SITE'):
            url_to_enroll = marketing_link('COURSES')
        else:
            url_to_enroll = reverse('about_course', args=[self.get_course_key()])

        data.update({
            'form': self.get_form(),
            'has_valid_information': has_valid_university_id(self.request.user, unicode(self.get_course_key())),
            'is_form_disabled': is_student_form_disabled(self.request.user, self.get_course_key()),
            'show_enroll_banner': self.show_enroll_banner(),
            'terms_conditions': terms_and_conditions,
            'registration_end': registration_end_date,
            'url_to_enroll': url_to_enroll,
        })

        return data

    @method_decorator(transaction.non_atomic_requests)
    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures login and a valid course key.
        """
        return super(UniversityIDView, self).dispatch(*args, **kwargs)


class UniversityIDSettingsSuccessView(ContextMixin, generic.TemplateView):
    """
    Just a plain student university ID settings success view with a link to the course content.
    """
    template_name = 'edraak_university/instructor/settings_success.html'

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures login and a valid course key.
        """
        self.require_staff_access()
        return super(UniversityIDSettingsSuccessView, self).dispatch(*args, **kwargs)


class UniversityIDSuccessView(ContextMixin, generic.TemplateView):
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


class UniversityIDStaffView(ContextMixin, generic.FormView, generic.ListView):
    """
    A list of IDs for instructors to review and modify.
    """
    template_name = 'edraak_university/instructor/main.html'
    model = UniversityID
    form_class = forms.UniversityIDSettingsForm

    def get_success_url(self):
        return reverse('edraak_university:id_settings_success', kwargs={
            'course_id': self.kwargs['course_id'],
        })

    def get_queryset(self):
        return UniversityID.get_marked_university_ids(course_key=self.get_course_key())

    def get_initial(self):
        initial = super(UniversityIDStaffView, self).get_initial()
        inst = get_university_settings(self.get_course_key())

        if inst:
            initial = {
                'registration_end_date': inst.registration_end_date,
                'terms_and_conditions': inst.terms_and_conditions,
            }

        return initial

    def form_invalid(self, form):
        """
        When the form is invalid this method is rendering the response
        directly without setting the object list which causes an error.
        :param form: The invalid form.
        :return: The super render to response.

        Omar's note:
            I didn't do this, and I'm not sure if I can have the time to refactor it!
            The root cause of this is that (FormView and ListView) should not be used together.
        """
        self.object_list = self.get_queryset()
        return super(UniversityIDStaffView, self).form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super(UniversityIDStaffView, self).get_context_data()
        context['sections'] = [
            {
                'section_display_name': 'Students\' IDs List',
                'section_key': 'list'
            },
            {
                'section_display_name': 'University ID settings',
                'section_key': 'settings',
                'form': self.get_form()
            },
        ]
        return context

    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.course_key = self.get_course_key()
        instance.save()
        return super(UniversityIDStaffView, self).form_valid(form)

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures only staff has access to the module..
        """
        self.require_staff_access()
        return super(UniversityIDStaffView, self).dispatch(*args, **kwargs)


class UniversityIDUpdateView(ContextMixin, generic.UpdateView):
    """
    Instructor update view for the student ID.
    """
    model = UniversityID
    template_name = 'edraak_university/instructor/update.html'
    form_class = forms.UniversityIDInstructorForm

    def get_form_kwargs(self):
        kwargs = super(UniversityIDUpdateView, self).get_form_kwargs()
        instance = UniversityID.objects.get(pk=self.kwargs['pk'])

        kwargs['instance'] = instance
        kwargs['course_key'] = self.get_course_key()

        return kwargs

    def get_success_url(self):
        return reverse('edraak_university:id_staff', kwargs={
            'course_id': self.get_course_key(),
        })

    def form_valid(self, form):
        instance = form.save(commit=False)
        instance.cohort = form.cleaned_data['cohort']
        instance.can_edit = False
        instance.save()

        try:
            add_user_to_cohort(get_cohort_by_id(self.get_course_key(), instance.cohort), instance.user.email)
        except ValueError:
            pass

        return super(UniversityIDUpdateView, self).form_valid(form)

    @method_decorator(transaction.non_atomic_requests)
    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures only staff has access to the module..
        """
        self.require_staff_access()
        return super(UniversityIDUpdateView, self).dispatch(*args, **kwargs)


class UniversityIDDeleteView(ContextMixin, generic.DeleteView):
    """
    Instructor delete view for the student ID.
    """
    model = UniversityID
    template_name = 'edraak_university/instructor/delete.html'

    def get_success_url(self):
        return reverse('edraak_university:id_staff', kwargs={
            'course_id': self.get_course_key(),
        })

    def delete(self, request, *args, **kwargs):
        university_id = self.get_object()
        university_id.remove_from_cohort()
        return super(UniversityIDDeleteView, self).delete(request, *args, **kwargs)

    @method_decorator(login_required)
    @method_decorator(ensure_valid_course_key)
    def dispatch(self, *args, **kwargs):
        """
        Ensures only staff has access to the module..
        """
        self.require_staff_access()
        return super(UniversityIDDeleteView, self).dispatch(*args, **kwargs)
