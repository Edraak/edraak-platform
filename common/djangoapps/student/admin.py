""" Django admin pages for student app """
from config_models.admin import ConfigurationModelAdmin
from django import forms
from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import ugettext_lazy as _
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey

from openedx.core.lib.courses import clean_course_id
from student.models import (
    CourseAccessRole,
    CourseEnrollment,
    CourseEnrollmentAllowed,
    DashboardConfiguration,
    LinkedInAddToProfileConfiguration,
    PendingNameChange,
    Registration,
    RegistrationCookieConfiguration,
    UserAttribute,
    UserProfile,
    UserTestGroup
)
from student.roles import REGISTERED_ACCESS_ROLES
from xmodule.modulestore.django import modulestore

User = get_user_model()  # pylint:disable=invalid-name


class CourseAccessRoleForm(forms.ModelForm):
    """Form for adding new Course Access Roles view the Django Admin Panel."""

    class Meta(object):
        model = CourseAccessRole
        fields = '__all__'

    email = forms.EmailField(required=True)
    COURSE_ACCESS_ROLES = [(role_name, role_name) for role_name in REGISTERED_ACCESS_ROLES.keys()]
    role = forms.ChoiceField(choices=COURSE_ACCESS_ROLES)

    def clean_course_id(self):
        """
        Validate the course id
        """
        if self.cleaned_data['course_id']:
            return clean_course_id(self)

    def clean_org(self):
        """If org and course-id exists then Check organization name
        against the given course.
        """
        if self.cleaned_data.get('course_id') and self.cleaned_data['org']:
            org = self.cleaned_data['org']
            org_name = self.cleaned_data.get('course_id').org
            if org.lower() != org_name.lower():
                raise forms.ValidationError(
                    u"Org name {} is not valid. Valid name is {}.".format(
                        org, org_name
                    )
                )

        return self.cleaned_data['org']

    def clean_email(self):
        """
        Checking user object against given email id.
        """
        email = self.cleaned_data['email']
        try:
            user = User.objects.get(email=email)
        except Exception:
            raise forms.ValidationError(
                u"Email does not exist. Could not find {email}. Please re-enter email address".format(
                    email=email
                )
            )

        return user

    def clean(self):
        """
        Checking the course already exists in db.
        """
        cleaned_data = super(CourseAccessRoleForm, self).clean()
        if not self.errors:
            if CourseAccessRole.objects.filter(
                    user=cleaned_data.get("email"),
                    org=cleaned_data.get("org"),
                    course_id=cleaned_data.get("course_id"),
                    role=cleaned_data.get("role")
            ).exists():
                raise forms.ValidationError("Duplicate Record.")

        return cleaned_data

    def __init__(self, *args, **kwargs):
        super(CourseAccessRoleForm, self).__init__(*args, **kwargs)
        if self.instance.user_id:
            self.fields['email'].initial = self.instance.user.email


@admin.register(CourseAccessRole)
class CourseAccessRoleAdmin(admin.ModelAdmin):
    """Admin panel for the Course Access Role. """
    form = CourseAccessRoleForm
    raw_id_fields = ("user",)
    exclude = ("user",)

    fieldsets = (
        (None, {
            'fields': ('email', 'course_id', 'org', 'role',)
        }),
    )

    list_display = (
        'id', 'user', 'org', 'course_id', 'role',
    )
    search_fields = (
        'id', 'user__username', 'user__email', 'org', 'course_id', 'role',
    )

    def save_model(self, request, obj, form, change):
        obj.user = form.cleaned_data['email']
        super(CourseAccessRoleAdmin, self).save_model(request, obj, form, change)


@admin.register(LinkedInAddToProfileConfiguration)
class LinkedInAddToProfileConfigurationAdmin(admin.ModelAdmin):
    """Admin interface for the LinkedIn Add to Profile configuration. """

    class Meta(object):
        model = LinkedInAddToProfileConfiguration

    # Exclude deprecated fields
    exclude = ('dashboard_tracking_code',)


class CourseEnrollmentForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(CourseEnrollmentForm, self).__init__(*args, **kwargs)

        if self.data.get('course'):
            try:
                self.data['course'] = CourseKey.from_string(self.data['course'])
            except InvalidKeyError:
                raise forms.ValidationError("Cannot make a valid CourseKey from id {}!".format(self.data['course']))

    def clean_course_id(self):
        course_id = self.cleaned_data['course']
        try:
            course_key = CourseKey.from_string(course_id)
        except InvalidKeyError:
            raise forms.ValidationError("Cannot make a valid CourseKey from id {}!".format(course_id))

        if not modulestore().has_course(course_key):
            raise forms.ValidationError("Cannot find course with id {} in the modulestore".format(course_id))

        return course_key

    class Meta:
        model = CourseEnrollment
        fields = '__all__'


# Page disabled because it makes DB quries that impact performance enough to
# cause a site outage. It may be re-enabled when it is updated to make more
# efficent DB queries
# https://openedx.atlassian.net/browse/OPS-2943
# Learner ticket to add functionality to /support
# https://openedx.atlassian.net/browse/LEARNER-4744
#@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    """ Admin interface for the CourseEnrollment model. """
    list_display = ('id', 'course_id', 'mode', 'user', 'is_active',)
    list_filter = ('mode', 'is_active',)
    raw_id_fields = ('user',)
    search_fields = ('course__id', 'mode', 'user__username',)
    form = CourseEnrollmentForm

    def queryset(self, request):
        return super(CourseEnrollmentAdmin, self).queryset(request).select_related('user')


class UserProfileInline(admin.StackedInline):
    """ Inline admin interface for UserProfile model. """
    model = UserProfile
    can_delete = False
    verbose_name_plural = _('User profile')


class UserAdmin(BaseUserAdmin):
    """ Admin interface for the User model. """
    inlines = (UserProfileInline,)
    # EDRAAK SPCIFIC overrid to remove groups from the filters
    list_filter = ('is_staff', 'is_superuser', 'is_active')
    filter_horizontal = ('user_permissions',)
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'email')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser',
                                        'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    # END EDRAAK SPECIFIC
    def get_readonly_fields(self, request, obj=None):
        """
        Allows editing the users while skipping the username check, so we can have Unicode username with no problems.
        The username is marked read-only when editing existing users regardless of `ENABLE_UNICODE_USERNAME`, to simplify the bokchoy tests.
        """
        django_readonly = super(UserAdmin, self).get_readonly_fields(request, obj)
        if obj:
            return django_readonly + ('username',)
        return django_readonly


@admin.register(UserAttribute)
class UserAttributeAdmin(admin.ModelAdmin):
    """ Admin interface for the UserAttribute model. """
    list_display = ('user', 'name', 'value',)
    list_filter = ('name',)
    raw_id_fields = ('user',)
    search_fields = ('name', 'value', 'user__username',)

    class Meta(object):
        model = UserAttribute


@admin.register(CourseEnrollmentAllowed)
class CourseEnrollmentAllowedAdmin(admin.ModelAdmin):
    """ Admin interface for the CourseEnrollmentAllowed model. """
    list_display = ('email', 'course_id', 'auto_enroll',)
    search_fields = ('email', 'course_id',)

    class Meta(object):
        model = CourseEnrollmentAllowed


admin.site.register(UserTestGroup)
admin.site.register(Registration)
admin.site.register(PendingNameChange)
admin.site.register(DashboardConfiguration, ConfigurationModelAdmin)
admin.site.register(RegistrationCookieConfiguration, ConfigurationModelAdmin)


# We must first un-register the User model since it may also be registered by the auth app.
try:
    admin.site.unregister(User)
except NotRegistered:
    pass

admin.site.register(User, UserAdmin)
