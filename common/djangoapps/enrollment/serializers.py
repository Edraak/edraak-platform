"""
Serializers for all Course Enrollment related return objects.
"""
import logging

from rest_framework import serializers

from course_modes.models import CourseMode
from course_api.serializers import CourseDetailMarketingSerializer as EdraakCourseSerializer
from student.models import CourseEnrollment
from bulk_email.models import Optout

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


class CourseEnrollmentsApiListSerializer(CourseEnrollmentSerializer):
    """
    Serializes CourseEnrollment model and returns a subset of fields returned
    by the CourseEnrollmentSerializer.
    """
    course_id = serializers.CharField(source='course_overview.id')

    def __init__(self, *args, **kwargs):
        super(CourseEnrollmentsApiListSerializer, self).__init__(*args, **kwargs)
        self.fields.pop('course_details')

    class Meta(CourseEnrollmentSerializer.Meta):
        fields = CourseEnrollmentSerializer.Meta.fields + ('course_id', )


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
    edraak_course_details = EdraakCourseSerializer(source="course_overview")
    is_certificate_allowed = serializers.SerializerMethodField()
    specialization_slug = serializers.SerializerMethodField()
    subscribed_to_emails = serializers.SerializerMethodField()

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
            'subscribed_to_emails'
        )
        lookup_field = 'username'
