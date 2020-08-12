"""
Django REST Framework serializers for the User API Accounts sub-application
"""
import json
import logging

from rest_framework import serializers
from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from six import text_type

from lms.djangoapps.badges.utils import badges_enabled
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from openedx.core.djangoapps.user_api import errors
from openedx.core.djangoapps.user_api.accounts.utils import is_secondary_email_feature_enabled_for_user
from openedx.core.djangoapps.user_api.models import (
    RetirementState,
    UserPreference,
    UserRetirementStatus
)
from openedx.core.djangoapps.user_api.serializers import ReadOnlyFieldsSerializerMixin
from student.models import UserProfile, LanguageProficiency, SocialLink

from . import (
    NAME_MIN_LENGTH, ACCOUNT_VISIBILITY_PREF_KEY, PRIVATE_VISIBILITY,
    ALL_USERS_VISIBILITY,
)
from .image_helpers import get_profile_image_urls_for_user
from .utils import validate_social_link, format_social_link

PROFILE_IMAGE_KEY_PREFIX = 'image_url'
LOGGER = logging.getLogger(__name__)


class LanguageProficiencySerializer(serializers.ModelSerializer):
    """
    Class that serializes the LanguageProficiency model for account
    information.
    """
    class Meta(object):
        model = LanguageProficiency
        fields = ("code",)

    def get_identity(self, data):
        """
        This is used in bulk updates to determine the identity of an object.
        The default is to use the id of an object, but we want to override that
        and consider the language code to be the canonical identity of a
        LanguageProficiency model.
        """
        try:
            return data.get('code', None)
        except AttributeError:
            return None


class SocialLinkSerializer(serializers.ModelSerializer):
    """
    Class that serializes the SocialLink model for the UserProfile object.
    """
    class Meta(object):
        model = SocialLink
        fields = ("platform", "social_link")


class UserReadOnlySerializer(serializers.Serializer):
    """
    Class that serializes the User model and UserProfile model together.
    """
    def __init__(self, *args, **kwargs):
        # Don't pass the 'configuration' arg up to the superclass
        self.configuration = kwargs.pop('configuration', None)
        if not self.configuration:
            self.configuration = settings.ACCOUNT_VISIBILITY_CONFIGURATION

        # Don't pass the 'custom_fields' arg up to the superclass
        self.custom_fields = kwargs.pop('custom_fields', [])

        super(UserReadOnlySerializer, self).__init__(*args, **kwargs)

    def to_representation(self, user):
        """
        Overwrite to_native to handle custom logic since we are serializing three models as one here
        :param user: User object
        :return: Dict serialized account
        """
        try:
            user_profile = user.profile
        except ObjectDoesNotExist:
            user_profile = None
            LOGGER.warning("user profile for the user [%s] does not exist", user.username)

        try:
            account_recovery = user.account_recovery
        except ObjectDoesNotExist:
            account_recovery = None

        accomplishments_shared = badges_enabled()

        data = {
            "username": user.username,
            "url": self.context.get('request').build_absolute_uri(
                reverse('accounts_api', kwargs={'username': user.username})
            ),
            "email": user.email,
            # For backwards compatibility: Tables created after the upgrade to Django 1.8 will save microseconds.
            # However, mobile apps are not expecting microsecond in the serialized value. If we set it to zero the
            # DRF JSONEncoder will not include it in the serialized value.
            # https://docs.djangoproject.com/en/1.8/ref/databases/#fractional-seconds-support-for-time-and-datetime-fields
            "date_joined": user.date_joined.replace(microsecond=0),
            "is_active": user.is_active,
            "bio": None,
            "country": None,
            "profile_image": None,
            "language_proficiencies": None,
            "name": None,
            "gender": None,
            "goals": None,
            "year_of_birth": None,
            "level_of_education": None,
            "mailing_address": None,
            "requires_parental_consent": None,
            "accomplishments_shared": accomplishments_shared,
            "account_privacy": self.configuration.get('default_visibility'),
            "social_links": None,
            "extended_profile_fields": None,
        }

        if user_profile:
            data.update(
                {
                    "bio": AccountLegacyProfileSerializer.convert_empty_to_None(user_profile.bio),
                    "country": AccountLegacyProfileSerializer.convert_empty_to_None(user_profile.country.code),
                    "profile_image": AccountLegacyProfileSerializer.get_profile_image(
                        user_profile, user, self.context.get('request')
                    ),
                    "language_proficiencies": LanguageProficiencySerializer(
                        user_profile.language_proficiencies.all(), many=True
                    ).data,
                    "name": user_profile.name,
                    "gender": AccountLegacyProfileSerializer.convert_empty_to_None(user_profile.gender),
                    "goals": user_profile.goals,
                    "year_of_birth": user_profile.year_of_birth,
                    "level_of_education": AccountLegacyProfileSerializer.convert_empty_to_None(
                        user_profile.level_of_education
                    ),
                    "mailing_address": user_profile.mailing_address,
                    "requires_parental_consent": user_profile.requires_parental_consent(),
                    "account_privacy": get_profile_visibility(user_profile, user, self.configuration),
                    "social_links": SocialLinkSerializer(
                        user_profile.social_links.all(), many=True
                    ).data,
                    "extended_profile": get_extended_profile(user_profile),
                }
            )

        if account_recovery:
            if is_secondary_email_feature_enabled_for_user(user):
                data.update(
                    {
                        "secondary_email": account_recovery.secondary_email,
                    }
                )

        if self.custom_fields:
            fields = self.custom_fields
        elif user_profile:
            fields = _visible_fields(user_profile, user, self.configuration)
        else:
            fields = self.configuration.get('public_fields')

        return self._filter_fields(
            fields,
            data
        )

    def _filter_fields(self, field_whitelist, serialized_account):
        """
        Filter serialized account Dict to only include whitelisted keys
        """
        visible_serialized_account = {}

        for field_name in field_whitelist:
            visible_serialized_account[field_name] = serialized_account.get(field_name, None)

        return visible_serialized_account


class AccountUserSerializer(serializers.HyperlinkedModelSerializer, ReadOnlyFieldsSerializerMixin):
    """
    Class that serializes the portion of User model needed for account information.
    """
    class Meta(object):
        model = User
        fields = ("username", "email", "date_joined", "is_active")
        read_only_fields = ("username", "email", "date_joined", "is_active")
        explicit_read_only_fields = ()


class AccountLegacyProfileSerializer(serializers.HyperlinkedModelSerializer, ReadOnlyFieldsSerializerMixin):
    """
    Class that serializes the portion of UserProfile model needed for account information.
    """
    profile_image = serializers.SerializerMethodField("_get_profile_image")
    requires_parental_consent = serializers.SerializerMethodField()
    language_proficiencies = LanguageProficiencySerializer(many=True, required=False)
    social_links = SocialLinkSerializer(many=True, required=False)

    class Meta(object):
        model = UserProfile
        fields = (
            "name", "gender", "goals", "year_of_birth", "level_of_education", "country", "social_links",
            "mailing_address", "bio", "profile_image", "requires_parental_consent", "language_proficiencies"
        )
        # Currently no read-only field, but keep this so view code doesn't need to know.
        read_only_fields = ()
        explicit_read_only_fields = ("profile_image", "requires_parental_consent")

    def validate_name(self, new_name):
        """ Enforce minimum length for name. """
        if len(new_name) < NAME_MIN_LENGTH:
            raise serializers.ValidationError(
                "The name field must be at least {} characters long.".format(NAME_MIN_LENGTH)
            )
        return new_name

    def validate_language_proficiencies(self, value):
        """
        Enforce all languages are unique.
        """
        language_proficiencies = [language for language in value]
        unique_language_proficiencies = set(language["code"] for language in language_proficiencies)
        if len(language_proficiencies) != len(unique_language_proficiencies):
            raise serializers.ValidationError("The language_proficiencies field must consist of unique languages.")
        return value

    def validate_social_links(self, value):
        """
        Enforce only one entry for a particular social platform.
        """
        social_links = [social_link for social_link in value]
        unique_social_links = set(social_link["platform"] for social_link in social_links)
        if len(social_links) != len(unique_social_links):
            raise serializers.ValidationError("The social_links field must consist of unique social platforms.")
        return value

    def transform_gender(self, user_profile, value):  # pylint: disable=unused-argument
        """
        Converts empty string to None, to indicate not set. Replaced by to_representation in version 3.
        """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    def transform_country(self, user_profile, value):  # pylint: disable=unused-argument
        """
        Converts empty string to None, to indicate not set. Replaced by to_representation in version 3.
        """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    def transform_level_of_education(self, user_profile, value):  # pylint: disable=unused-argument
        """
        Converts empty string to None, to indicate not set. Replaced by to_representation in version 3.
        """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    def transform_bio(self, user_profile, value):  # pylint: disable=unused-argument
        """
        Converts empty string to None, to indicate not set. Replaced by to_representation in version 3.
        """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    @staticmethod
    def convert_empty_to_None(value):
        """
        Helper method to convert empty string to None (other values pass through).
        """
        return None if value == "" else value

    @staticmethod
    def get_profile_image(user_profile, user, request=None):
        """
        Returns metadata about a user's profile image.
        """
        data = {'has_image': user_profile.has_profile_image}
        urls = get_profile_image_urls_for_user(user, request)
        data.update({
            '{image_key_prefix}_{size}'.format(image_key_prefix=PROFILE_IMAGE_KEY_PREFIX, size=size_display_name): url
            for size_display_name, url in urls.items()
        })
        return data

    def get_requires_parental_consent(self, user_profile):
        """
        Returns a boolean representing whether the user requires parental controls.
        """
        return user_profile.requires_parental_consent()

    def _get_profile_image(self, user_profile):
        """
        Returns metadata about a user's profile image

        This protected method delegates to the static 'get_profile_image' method
        because 'serializers.SerializerMethodField("_get_profile_image")' will
        call the method with a single argument, the user_profile object.
        """
        return AccountLegacyProfileSerializer.get_profile_image(user_profile, user_profile.user)

    def update(self, instance, validated_data):
        """
        Update the profile, including nested fields.

        Raises:
        errors.AccountValidationError: the update was not attempted because validation errors were found with
            the supplied update
        """
        language_proficiencies = validated_data.pop("language_proficiencies", None)

        # Update all fields on the user profile that are writeable,
        # except for "language_proficiencies" and "social_links", which we'll update separately
        update_fields = set(self.get_writeable_fields()) - set(["language_proficiencies"]) - set(["social_links"])
        for field_name in update_fields:
            default = getattr(instance, field_name)
            field_value = validated_data.get(field_name, default)
            setattr(instance, field_name, field_value)

        # Update the related language proficiency
        if language_proficiencies is not None:
            instance.language_proficiencies.all().delete()
            instance.language_proficiencies.bulk_create([
                LanguageProficiency(user_profile=instance, code=language["code"])
                for language in language_proficiencies
            ])

        # Update the user's social links
        social_link_data = self._kwargs['data']['social_links'] if 'social_links' in self._kwargs['data'] else None
        if social_link_data and len(social_link_data) > 0:
            new_social_link = social_link_data[0]
            current_social_links = list(instance.social_links.all())
            instance.social_links.all().delete()

            try:
                # Add the new social link with correct formatting
                validate_social_link(new_social_link['platform'], new_social_link['social_link'])
                formatted_link = format_social_link(new_social_link['platform'], new_social_link['social_link'])
                instance.social_links.bulk_create([
                    SocialLink(user_profile=instance, platform=new_social_link['platform'], social_link=formatted_link)
                ])
            except ValueError as err:
                # If we have encountered any validation errors, return them to the user.
                raise errors.AccountValidationError({
                    'social_links': {
                        "developer_message": u"Error thrown from adding new social link: '{}'".format(text_type(err)),
                        "user_message": text_type(err)
                    }
                })

            # Add back old links unless overridden by new link
            for current_social_link in current_social_links:
                if current_social_link.platform != new_social_link['platform']:
                    instance.social_links.bulk_create([
                        SocialLink(user_profile=instance, platform=current_social_link.platform,
                                   social_link=current_social_link.social_link)
                    ])

        instance.save()

        return instance


class RetirementUserProfileSerializer(serializers.ModelSerializer):
    """
    Serialize a small subset of UserProfile data for use in RetirementStatus APIs
    """
    class Meta(object):
        model = UserProfile
        fields = ('id', 'name')


class RetirementUserSerializer(serializers.ModelSerializer):
    """
    Serialize a small subset of User data for use in RetirementStatus APIs
    """
    profile = RetirementUserProfileSerializer(read_only=True)

    class Meta(object):
        model = User
        fields = ('id', 'username', 'email', 'profile')


class RetirementStateSerializer(serializers.ModelSerializer):
    """
    Serialize a small subset of RetirementState data for use in RetirementStatus APIs
    """
    class Meta(object):
        model = RetirementState
        fields = ('id', 'state_name', 'state_execution_order')


class UserRetirementStatusSerializer(serializers.ModelSerializer):
    """
    Perform serialization for the RetirementStatus model
    """
    user = RetirementUserSerializer(read_only=True)
    current_state = RetirementStateSerializer(read_only=True)
    last_state = RetirementStateSerializer(read_only=True)

    class Meta(object):
        model = UserRetirementStatus
        exclude = ['responses', ]


class UserRetirementPartnerReportSerializer(serializers.Serializer):
    """
    Perform serialization for the UserRetirementPartnerReportingStatus model
    """
    user_id = serializers.IntegerField()
    original_username = serializers.CharField()
    original_email = serializers.EmailField()
    original_name = serializers.CharField()
    orgs = serializers.ListField(child=serializers.CharField())
    created = serializers.DateTimeField()

    # Required overrides of abstract base class methods, but we don't use them
    def create(self, validated_data):
        pass

    def update(self, instance, validated_data):
        pass


def get_extended_profile(user_profile):
    """
    Returns the extended user profile fields stored in user_profile.meta
    """

    # pick the keys from the site configuration
    extended_profile_field_names = configuration_helpers.get_value('extended_profile_fields', [])

    try:
        extended_profile_fields_data = json.loads(user_profile.meta)
    except ValueError:
        extended_profile_fields_data = {}

    extended_profile = []
    for field_name in extended_profile_field_names:
        extended_profile.append({
            "field_name": field_name,
            "field_value": extended_profile_fields_data.get(field_name, "")
        })
    return extended_profile


def get_profile_visibility(user_profile, user, configuration=None):
    """
    Returns the visibility level for the specified user profile.
    """
    if user_profile.requires_parental_consent():
        return PRIVATE_VISIBILITY

    if not configuration:
        configuration = settings.ACCOUNT_VISIBILITY_CONFIGURATION

    # Calling UserPreference directly because the requesting user may be different from existing_user
    # (and does not have to be is_staff).
    profile_privacy = UserPreference.get_value(user, ACCOUNT_VISIBILITY_PREF_KEY)
    return profile_privacy if profile_privacy else configuration.get('default_visibility')


def _visible_fields(user_profile, user, configuration=None):
    """
    Return what fields should be visible based on user settings

    :param user_profile: User profile object
    :param user: User object
    :param configuration: A visibility configuration dictionary.
    :return: whitelist List of fields to be shown
    """

    if not configuration:
        configuration = settings.ACCOUNT_VISIBILITY_CONFIGURATION

    profile_visibility = get_profile_visibility(user_profile, user, configuration)
    if profile_visibility == ALL_USERS_VISIBILITY:
        return configuration.get('shareable_fields')
    else:
        return configuration.get('public_fields')
