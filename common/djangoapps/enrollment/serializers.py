"""
Serializers for all Course Enrollment related return objects.
"""
import logging

from rest_framework import serializers

from bulk_email.models import Optout
from course_modes.models import CourseMode
from course_api.serializers import CourseDetailMarketingSerializer
from student.models import CourseEnrollment

from edraak_specializations.models import CourseSpecializationInfo

log = logging.getLogger(__name__)


class StringListField(serializers.CharField):
    """Custom Serializer for turning a comma delimited string into a list.

    This field is designed to take a string such as "1,2,3" and turn it into an actual list
    [1,2,3]

    """
    def field_to_native(self, obj, field_name):
        """
        Serialize the object's class name.
        """
        if not obj.suggested_prices:
            return []

        items = obj.suggested_prices.split(',')
        return [int(item) for item in items]


class CourseSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serialize a course descriptor and related information.
    """

    course_id = serializers.CharField(source="id")
    course_name = serializers.CharField(source="display_name_with_default")
    enrollment_start = serializers.DateTimeField(format=None)
    enrollment_end = serializers.DateTimeField(format=None)
    course_start = serializers.DateTimeField(source="start", format=None)
    course_end = serializers.DateTimeField(source="end", format=None)
    invite_only = serializers.BooleanField(source="invitation_only")
    course_modes = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.include_expired = kwargs.pop("include_expired", False)
        super(CourseSerializer, self).__init__(*args, **kwargs)

    def get_course_modes(self, obj):
        """
        Retrieve course modes associated with the course.
        """
        course_modes = CourseMode.modes_for_course(
            obj.id,
            include_expired=self.include_expired,
            only_selectable=False
        )
        return [
            ModeSerializer(mode).data
            for mode in course_modes
        ]


class CourseEnrollmentSerializer(serializers.ModelSerializer):
    """Serializes CourseEnrollment models

    Aggregates all data from the Course Enrollment table, and pulls in the serialization for
    the Course Descriptor and course modes, to give a complete representation of course enrollment.

    """
    course_details = CourseSerializer(source="course_overview")
    user = serializers.SerializerMethodField('get_username')

    def get_username(self, model):
        """Retrieves the username from the associated model."""
        return model.username

    class Meta(object):
        model = CourseEnrollment
        fields = ('created', 'mode', 'is_active', 'course_details', 'user')
        lookup_field = 'username'


class ModeSerializer(serializers.Serializer):
    """Serializes a course's 'Mode' tuples

    Returns a serialized representation of the modes available for course enrollment. The course
    modes models are designed to return a tuple instead of the model object itself. This serializer
    does not handle the model object itself, but the tuple.

    """
    slug = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=255)
    min_price = serializers.IntegerField()
    suggested_prices = StringListField(max_length=255)
    currency = serializers.CharField(max_length=8)
    expiration_datetime = serializers.DateTimeField()
    description = serializers.CharField()
    sku = serializers.CharField()
    bulk_sku = serializers.CharField()


# Edraak: adding custom serializer for enrollments
class EdraakCourseEnrollmentSerializer(CourseEnrollmentSerializer):
    edraak_course_details = serializers.SerializerMethodField()
    is_certificate_allowed = serializers.SerializerMethodField()
    specialization_slug = serializers.SerializerMethodField()
    subscribed_to_emails = serializers.SerializerMethodField()
    is_completed = serializers.SerializerMethodField()
    is_certificate_available = serializers.SerializerMethodField()

    def get_edraak_course_details(self, obj):
        context = self.context.copy()
        CourseDetailMarketingSerializer.update_marketing_context(
            context=context,
            course_key=obj.course_id
        )

        return CourseDetailMarketingSerializer(
            obj.course_overview,
            context=context
        ).data

    def _get_user(self):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            return request.user
        return None

    def get_is_certificate_allowed(self, obj):
        # Keep this import local to hide LMS related stuff from pytest when testing CMS
        from edraak_certificates.utils import is_certificate_allowed

        user = self._get_user()
        if user:
            allowed = obj.course_overview and is_certificate_allowed(user, obj.course_overview)
        else:
            log.warning(
                'EDRAAK: Certificate is not allowed because EdraakCourseEnrollmentSerializer cannot find user!'
            )
            allowed = False

        return allowed

    def get_specialization_slug(self, obj):
        try:
            specialization_info = CourseSpecializationInfo.objects.get(course_id=obj.course_id)
        except CourseSpecializationInfo.DoesNotExist:
            return None
        return specialization_info.specialization_slug

    def get_subscribed_to_emails(self, obj):
        user = self._get_user()
        if not user or not user.is_authenticated:
            return False

        return not Optout.objects.filter(user=user, course_id=obj.course_id).exists()

    def get_is_completed(self, obj):
        # Keep this import local to hide LMS related stuff from pytest when testing CMS
        from lms.djangoapps.grades.models import PersistentCourseGrade

        user = self._get_user()
        completed = False
        if user:
            try:
                grade = PersistentCourseGrade.objects.get(
                    user_id=user.id,
                    course_id=obj.course_id,
                )
            except PersistentCourseGrade.DoesNotExist:
                pass
            else:
                if grade.percent_grade >= float(obj.course_overview.lowest_passing_grade):
                    completed = True
        return completed

    def get_is_certificate_available(self, obj):
        # Keep this import local to hide LMS related stuff from pytest when testing CMS
        from lms.djangoapps.certificates.models import CertificateStatuses, GeneratedCertificate

        user = self._get_user()
        available = False
        if user:
            try:
                _ = GeneratedCertificate.objects.get(
                    user_id=user.id,
                    course_id=obj.course_id,
                    status__in=[CertificateStatuses.downloadable, CertificateStatuses.error],
                )
            except GeneratedCertificate.DoesNotExist:
                pass
            else:
                available = True
        return available

    class Meta(object):
        model = CourseEnrollment
        fields = (
            'created',
            'mode',
            'is_active',
            'course_details',
            'edraak_course_details',
            'is_certificate_allowed',
            'specialization_slug',
            'user',
            'subscribed_to_emails',
            'is_completed',
            'is_certificate_available',
        )
        lookup_field = 'username'
