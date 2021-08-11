"""
Course API Serializers.  Representing course catalog data
"""

import urllib

from django.urls import reverse
from django.utils.translation import get_language
from rest_framework import serializers

from course_api.helpers import get_marketing_data, is_marketing_api_enabled
from openedx.core.djangoapps.models.course_details import CourseDetails
from openedx.core.lib.api.fields import AbsoluteURLField


class _MediaSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Nested serializer to represent a media object.
    """

    def __init__(self, uri_attribute, *args, **kwargs):
        super(_MediaSerializer, self).__init__(*args, **kwargs)
        self.uri_attribute = uri_attribute

    uri = serializers.SerializerMethodField(source='*')

    def get_uri(self, course_overview):
        """
        Get the representation for the media resource's URI
        """
        return getattr(course_overview, self.uri_attribute)


class ImageSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Collection of URLs pointing to images of various sizes.

    The URLs will be absolute URLs with the host set to the host of the current request. If the values to be
    serialized are already absolute URLs, they will be unchanged.
    """
    raw = AbsoluteURLField()
    small = AbsoluteURLField()
    large = AbsoluteURLField()


class _CourseApiMediaCollectionSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Nested serializer to represent a collection of media objects
    """
    course_image = _MediaSerializer(source='*', uri_attribute='course_image_url')
    course_video = _MediaSerializer(source='*', uri_attribute='course_video_url')
    image = ImageSerializer(source='image_urls')


class CourseSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for Course objects providing minimal data about the course.
    Compare this with CourseDetailSerializer.
    """

    blocks_url = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    effort = serializers.CharField()
    end = serializers.DateTimeField()
    enrollment_start = serializers.DateTimeField()
    enrollment_end = serializers.DateTimeField()
    id = serializers.CharField()  # pylint: disable=invalid-name
    media = _CourseApiMediaCollectionSerializer(source='*')
    name = serializers.CharField(source='display_name_with_default_escaped')
    name_en = serializers.CharField(read_only=True)
    name_ar = serializers.CharField(read_only=True)
    number = serializers.CharField(source='display_number_with_default')
    org = serializers.CharField(source='display_org_with_default')
    short_description = serializers.CharField()
    start = serializers.DateTimeField()
    start_display = serializers.CharField()
    start_type = serializers.CharField()
    pacing = serializers.CharField()
    mobile_available = serializers.BooleanField()
    hidden = serializers.SerializerMethodField()
    invitation_only = serializers.BooleanField()

    # 'course_id' is a deprecated field, please use 'id' instead.
    course_id = serializers.CharField(source='id', read_only=True)
    def __init__(self, *args, **kwargs):
        super(CourseSerializer, self).__init__(*args, **kwargs)

        context = kwargs.get('context')
        if context:
            calculate_completion = context.get('calculate_completion')
            if calculate_completion:
                self.fields['completed'] = serializers.SerializerMethodField()

    def get_hidden(self, course_overview):
        """
        Get the representation for SerializerMethodField `hidden`
        Represents whether course is hidden in LMS
        """
        catalog_visibility = course_overview.catalog_visibility
        return catalog_visibility in ['about', 'none']

    def get_blocks_url(self, course_overview):
        """
        Get the representation for SerializerMethodField `blocks_url`
        """
        base_url = '?'.join([
            reverse('blocks_in_course'),
            urllib.urlencode({'course_id': course_overview.id}),
        ])
        return self.context['request'].build_absolute_uri(base_url)

    def get_duration(self, obj):
        if obj.self_paced:
            return 0

        try:
            delta = obj.end - obj.start
            return int(delta.days / 7)
        except TypeError:
            return 0

    def get_completed(self, obj):
        from edraak_certificates.utils import is_student_pass

        request = self.context['request']
        course_id_str = str(obj.id)
        return bool(is_student_pass(request.user, course_id_str))


class CourseDetailMarketingSerializer(CourseSerializer):
    """
    Serializer for Course objects (like CourseDetailSerializer) but fetching some data from the marketing site.

    This allows reuse of the marketing site data, as opposed to duplicating them in the LMS.
    """
    @staticmethod
    def update_marketing_context(context, course_key):
        from enrollment import time_block
        with time_block('CourseDetailMarketingSerializer.update_marketing_context', 5):
            if is_marketing_api_enabled():
                lang = 'en'
                if context.get('request') and hasattr(context['request'], 'LANGUAGE_CODE'):
                    lang = context['request'].LANGUAGE_CODE
                context['marketing_data'] = get_marketing_data(
                    course_key=course_key,
                    language=lang,
                )

    def get_data_with_marketing_overrides(self, original_serialized_data):
        from enrollment import time_block
        with time_block('CourseDetailMarketingSerializer.get_data_with_marketing_overrides', 5):
            marketing_data = self.context.get('marketing_data')
            if not marketing_data:
                return original_serialized_data

            overridden = {}
            overridden.update(original_serialized_data)

            overridden['effort'] = marketing_data['effort']
            overridden['name'] = marketing_data['name']
            if get_language() == 'en':
                overridden['short_description'] = marketing_data['short_description_en']
            else:
                overridden['short_description'] = marketing_data['short_description_ar']
            overridden['overview'] = marketing_data['overview'] or ''
            overridden['name_en'] = marketing_data['name_en']
            overridden['name_ar'] = marketing_data['name_ar']

            if marketing_data.get('course_image'):
                overridden['media']['course_image']['uri'] = marketing_data['course_image']

            if marketing_data.get('course_video'):
                overridden['media']['course_video']['uri'] = marketing_data['course_video']

            return overridden

    @property
    def data(self):
        from enrollment import time_block
        with time_block('CourseDetailMarketingSerializer.data', 5):
            serialized_data = super(CourseDetailMarketingSerializer, self).data
            return self.get_data_with_marketing_overrides(serialized_data)


class CourseDetailSerializer(CourseSerializer):  # pylint: disable=abstract-method
    """
    Serializer for Course objects providing additional details about the
    course.

    This serializer makes additional database accesses (to the modulestore) and
    returns more data (including 'overview' text). Therefore, for performance
    and bandwidth reasons, it is expected that this serializer is used only
    when serializing a single course, and not for serializing a list of
    courses.
    """

    overview = serializers.SerializerMethodField()

    def get_overview(self, course_overview):
        """
        Get the representation for SerializerMethodField `overview`
        """
        # Note: This makes a call to the modulestore, unlike the other
        # fields from CourseSerializer, which get their data
        # from the CourseOverview object in SQL.
        return CourseDetails.fetch_about_attribute(course_overview.id, 'overview')
