import six
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.translation import ugettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty

from cms.djangoapps.contentstore.views.course import create_new_course, get_course_and_check_access, rerun_course
from contentstore.views.assets import update_course_run_asset
from openedx.core.lib.courses import course_image_url
from student.models import CourseAccessRole
from xmodule.modulestore.django import modulestore

IMAGE_TYPES = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
}
User = get_user_model()


class CourseAccessRoleSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(slug_field='username', queryset=User.objects.all())

    class Meta:
        model = CourseAccessRole
        fields = ('user', 'role',)


class CourseRunScheduleSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    enrollment_start = serializers.DateTimeField(allow_null=True, required=False)
    enrollment_end = serializers.DateTimeField(allow_null=True, required=False)


class CourseRunTeamSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        """Overriding this to support deserialization, for write operations."""
        for member in data:
            try:
                User.objects.get(username=member['user'])
            except User.DoesNotExist:
                raise serializers.ValidationError(
                    _('Course team user does not exist')
                )

        return CourseAccessRoleSerializer(data=data, many=True).to_internal_value(data)

    def to_representation(self, instance):
        roles = CourseAccessRole.objects.filter(course_id=instance.id)
        return CourseAccessRoleSerializer(roles, many=True).data

    def get_attribute(self, instance):
        # Course instances have no "team" attribute. Return the course, and the consuming serializer will
        # handle the rest.
        return instance


class CourseRunTeamSerializerMixin(serializers.Serializer):
    team = CourseRunTeamSerializer(required=False)

    def update_team(self, instance, team):
        # Existing data should remain intact when performing a partial update.
        if not self.partial:
            CourseAccessRole.objects.filter(course_id=instance.id).delete()

        # We iterate here, instead of using a bulk operation, to avoid uniqueness errors that arise
        # when using `bulk_create` with existing data. Given the relatively small number of team members
        # in a course, this is not worth optimizing at this time.
        for member in team:
            CourseAccessRole.objects.get_or_create(
                course_id=instance.id,
                org=instance.id.org,
                user=User.objects.get(username=member['user']),
                role=member['role']
            )


def image_is_jpeg_or_png(value):
    content_type = value.content_type
    if content_type not in IMAGE_TYPES.keys():
        raise serializers.ValidationError(
            'Only JPEG and PNG image types are supported. {} is not valid'.format(content_type))


class CourseRunImageField(serializers.ImageField):
    default_validators = [image_is_jpeg_or_png]

    def get_attribute(self, instance):
        return course_image_url(instance)

    def to_representation(self, value):
        # Value will always be the URL path of the image.
        request = self.context['request']
        return request.build_absolute_uri(value)


class CourseRunPacingTypeField(serializers.ChoiceField):
    def to_representation(self, value):
        return 'self_paced' if value else 'instructor_paced'

    def to_internal_value(self, data):
        return data == 'self_paced'


class CourseRunImageSerializer(serializers.Serializer):
    # We set an empty default to prevent the parent serializer from attempting
    # to save this value to the Course object.
    card_image = CourseRunImageField(source='course_image', default=empty)

    def update(self, instance, validated_data):
        course_image = validated_data['course_image']
        course_image.name = 'course_image.' + IMAGE_TYPES[course_image.content_type]
        update_course_run_asset(instance.id, course_image)

        instance.course_image = course_image.name
        modulestore().update_item(instance, self.context['request'].user.id)
        return instance


class CourseRunSerializerCommonFieldsMixin(serializers.Serializer):
    schedule = CourseRunScheduleSerializer(source='*', required=False)
    pacing_type = CourseRunPacingTypeField(source='self_paced', required=False,
                                           choices=(('instructor_paced', False), ('self_paced', True),))


class CourseRunSerializer(CourseRunSerializerCommonFieldsMixin, CourseRunTeamSerializerMixin, serializers.Serializer):
    id = serializers.CharField(read_only=True)
    title = serializers.CharField(source='display_name')
    images = CourseRunImageSerializer(source='*', required=False)

    def update(self, instance, validated_data):
        team = validated_data.pop('team', [])

        with transaction.atomic():
            self.update_team(instance, team)

            for attr, value in six.iteritems(validated_data):
                setattr(instance, attr, value)

            modulestore().update_item(instance, self.context['request'].user.id)
            return instance


class CourseRunCreateSerializer(CourseRunSerializer):
    org = serializers.CharField(source='id.org')
    number = serializers.CharField(source='id.course')
    run = serializers.CharField(source='id.run')

    def create(self, validated_data):
        _id = validated_data.pop('id')
        team = validated_data.pop('team', [])
        user = self.context['request'].user

        with transaction.atomic():
            instance = create_new_course(user, _id['org'], _id['course'], _id['run'], validated_data)
            self.update_team(instance, team)
            return instance


class CourseRunRerunSerializer(CourseRunSerializerCommonFieldsMixin, CourseRunTeamSerializerMixin,
                               serializers.Serializer):
    title = serializers.CharField(source='display_name', required=False)
    run = serializers.CharField(source='id.run')

    def validate_run(self, value):
        course_run_key = self.instance.id
        store = modulestore()
        with store.default_store('split'):
            new_course_run_key = store.make_course_key(course_run_key.org, course_run_key.course, value)
        if store.has_course(new_course_run_key, ignore_case=True):
            raise serializers.ValidationError('Course run {key} already exists'.format(key=new_course_run_key))
        return value

    def update(self, instance, validated_data):
        course_run_key = instance.id
        _id = validated_data.pop('id')
        team = validated_data.pop('team', [])
        user = self.context['request'].user
        fields = {
            'display_name': instance.display_name
        }
        fields.update(validated_data)
        new_course_run_key = rerun_course(user, course_run_key, course_run_key.org, course_run_key.course, _id['run'],
                                          fields, background=False)

        course_run = get_course_and_check_access(new_course_run_key, user)
        self.update_team(course_run, team)
        return course_run
