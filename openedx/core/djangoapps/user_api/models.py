"""
Django ORM model specifications for the User API application
"""
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver
from model_utils.models import TimeStampedModel
from opaque_keys.edx.django.models import CourseKeyField
from openedx.core.djangolib.model_mixins import DeletableByUserValue

# Currently, the "student" app is responsible for
# accounts, profiles, enrollments, and the student dashboard.
# We are trying to move some of this functionality into separate apps,
# but currently the rest of the system assumes that "student" defines
# certain models.  For now we will leave the models in "student" and
# create an alias in "user_api".

# pylint: disable=unused-import
from student.models import (
    PendingEmailChange,
    Registration,
    UserProfile,
    get_retired_email_by_email,
    get_retired_username_by_username
)
from util.model_utils import emit_setting_changed_event, get_changed_fields_dict


class RetirementStateError(Exception):
    pass


class UserPreference(models.Model):
    """A user's preference, stored as generic text to be processed by client"""
    KEY_REGEX = r"[-_a-zA-Z0-9]+"
    user = models.ForeignKey(User, db_index=True, related_name="preferences", on_delete=models.CASCADE)
    key = models.CharField(max_length=255, db_index=True, validators=[RegexValidator(KEY_REGEX)])
    value = models.TextField()

    class Meta(object):
        unique_together = ("user", "key")

    @staticmethod
    def get_all_preferences(user):
        """
        Gets all preferences for a given user

        Returns: Set of (preference type, value) pairs for each of the user's preferences
        """
        return dict([(pref.key, pref.value) for pref in user.preferences.all()])

    @classmethod
    def get_value(cls, user, preference_key, default=None):
        """Gets the user preference value for a given key.

        Note:
            This method provides no authorization of access to the user preference.
            Consider using user_api.preferences.api.get_user_preference instead if
            this is part of a REST API request.

        Arguments:
            user (User): The user whose preference should be set.
            preference_key (str): The key for the user preference.
            default: The object to return if user does not have preference key set

        Returns:
            The user preference value, or default if one is not set.
        """
        try:
            user_preference = cls.objects.get(user=user, key=preference_key)
            return user_preference.value
        except cls.DoesNotExist:
            return default


@receiver(pre_save, sender=UserPreference)
def pre_save_callback(sender, **kwargs):
    """
    Event changes to user preferences.
    """
    user_preference = kwargs["instance"]
    user_preference._old_value = get_changed_fields_dict(user_preference, sender).get("value", None)


@receiver(post_save, sender=UserPreference)
def post_save_callback(sender, **kwargs):
    """
    Event changes to user preferences.
    """
    user_preference = kwargs["instance"]
    emit_setting_changed_event(
        user_preference.user, sender._meta.db_table, user_preference.key,
        user_preference._old_value, user_preference.value
    )
    user_preference._old_value = None


@receiver(post_delete, sender=UserPreference)
def post_delete_callback(sender, **kwargs):
    """
    Event changes to user preferences.
    """
    user_preference = kwargs["instance"]
    emit_setting_changed_event(
        user_preference.user, sender._meta.db_table, user_preference.key, user_preference.value, None
    )


class UserCourseTag(models.Model):
    """
    Per-course user tags, to be used by various things that want to store tags about
    the user.  Added initially to store assignment to experimental groups.
    """
    user = models.ForeignKey(User, db_index=True, related_name="+", on_delete=models.CASCADE)
    key = models.CharField(max_length=255, db_index=True)
    course_id = CourseKeyField(max_length=255, db_index=True)
    value = models.TextField()

    class Meta(object):
        unique_together = ("user", "course_id", "key")


class UserOrgTag(TimeStampedModel, DeletableByUserValue):  # pylint: disable=model-missing-unicode
    """
    Per-Organization user tags.

    Allows settings to be configured at an organization level.

    """
    user = models.ForeignKey(User, db_index=True, related_name="+", on_delete=models.CASCADE)
    key = models.CharField(max_length=255, db_index=True)
    org = models.CharField(max_length=255, db_index=True)
    value = models.TextField()

    class Meta(object):
        unique_together = ("user", "org", "key")


class RetirementState(models.Model):
    """
    Stores the list and ordering of the steps of retirement, this should almost never change
    as updating it can break the retirement process of users already in the queue.
    """
    state_name = models.CharField(max_length=30, unique=True)
    state_execution_order = models.SmallIntegerField(unique=True)
    is_dead_end_state = models.BooleanField(default=False, db_index=True)
    required = models.BooleanField(default=False)

    def __unicode__(self):
        return u'{} (step {})'.format(self.state_name, self.state_execution_order)

    class Meta(object):
        ordering = ('state_execution_order',)

    @classmethod
    def get_dead_end_states(cls):
        return cls.objects.filter(is_dead_end_state=True)

    @classmethod
    def get_dead_end_state_names_list(cls):
        return cls.objects.filter(is_dead_end_state=True).values_list('state_name', flat=True)

    @classmethod
    def get_state_names_list(cls):
        return cls.objects.all().values_list('state_name', flat=True)


class UserRetirementPartnerReportingStatus(TimeStampedModel):
    """
    When a user has been retired from LMS it will still need to be reported out to
    partners so they can forget the user also. This process happens on a very different,
    and asynchronous, timeline than LMS retirement and only impacts a subset of learners
    so it maintains a queue. This queue is populated as part of the LMS retirement
    process.
    """
    user = models.OneToOneField(User)
    original_username = models.CharField(max_length=150, db_index=True)
    original_email = models.EmailField(db_index=True)
    original_name = models.CharField(max_length=255, blank=True, db_index=True)
    is_being_processed = models.BooleanField(default=False)

    class Meta(object):
        verbose_name = 'User Retirement Reporting Status'
        verbose_name_plural = 'User Retirement Reporting Statuses'

    def __unicode__(self):
        return u'UserRetirementPartnerReportingStatus: {} is being processed: {}'.format(
            self.user,
            self.is_being_processed
        )


class UserRetirementRequest(TimeStampedModel):
    """
    Records and perists every user retirement request.
    Users that have requested to cancel their retirement before retirement begins can be removed.
    All other retired users persist in this table forever.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    class Meta(object):
        verbose_name = 'User Retirement Request'
        verbose_name_plural = 'User Retirement Requests'

    @classmethod
    def create_retirement_request(cls, user):
        """
        Creates a UserRetirementRequest for the specified user.
        """
        if cls.has_user_requested_retirement(user):
            raise RetirementStateError('User {} already has a retirement request row!'.format(user))
        return cls.objects.create(user=user)

    @classmethod
    def has_user_requested_retirement(cls, user):
        """
        Checks to see if a UserRetirementRequest has been created for the specified user.
        """
        return cls.objects.filter(user=user).exists()

    def __unicode__(self):
        return u'User: {} Requested: {}'.format(self.user.id, self.created)


class UserRetirementStatus(TimeStampedModel):
    """
    Tracks the progress of a user's retirement request
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    original_username = models.CharField(max_length=150, db_index=True)
    original_email = models.EmailField(db_index=True)
    original_name = models.CharField(max_length=255, blank=True, db_index=True)
    retired_username = models.CharField(max_length=150, db_index=True)
    retired_email = models.EmailField(db_index=True)
    current_state = models.ForeignKey(RetirementState, related_name='current_state', on_delete=models.CASCADE)
    last_state = models.ForeignKey(RetirementState, blank=True, related_name='last_state', on_delete=models.CASCADE)
    responses = models.TextField()

    class Meta(object):
        verbose_name = 'User Retirement Status'
        verbose_name_plural = 'User Retirement Statuses'

    def _validate_state_update(self, new_state):
        """
        Confirm that the state move that's trying to be made is allowed
        """
        dead_end_states = list(RetirementState.get_dead_end_state_names_list())
        states = list(RetirementState.get_state_names_list())
        if self.current_state in dead_end_states:
            raise RetirementStateError('RetirementStatus: Unable to move user from {}'.format(self.current_state))

        try:
            new_state_index = states.index(new_state)
            if new_state_index <= states.index(self.current_state.state_name):
                raise ValueError()
        except ValueError:
            err = '{} does not exist or is an eariler state than current state {}'.format(new_state, self.current_state)
            raise RetirementStateError(err)

    def _validate_update_data(self, data):
        """
        Confirm that the data passed in is properly formatted
        """
        required_keys = ('username', 'new_state', 'response')

        for required_key in required_keys:
            if required_key not in data:
                raise RetirementStateError('RetirementStatus: Required key {} missing from update'.format(required_key))

        for key in data:
            if key not in required_keys:
                raise RetirementStateError('RetirementStatus: Unknown key {} in update'.format(key))

    @classmethod
    def create_retirement(cls, user):
        """
        Creates a UserRetirementStatus for the given user, in the correct initial state. Will
        fail if the user already has a UserRetirementStatus row or if states are not yet populated.
        """
        try:
            pending = RetirementState.objects.all().order_by('state_execution_order')[0]
        except IndexError:
            raise RetirementStateError('Default state does not exist! Populate retirement states to retire users.')

        if cls.objects.filter(user=user).exists():
            raise RetirementStateError('User {} already has a retirement status row!'.format(user))

        retired_username = get_retired_username_by_username(user.username)
        retired_email = get_retired_email_by_email(user.email)

        UserRetirementRequest.create_retirement_request(user)

        return cls.objects.create(
            user=user,
            original_username=user.username,
            original_email=user.email,
            original_name=user.profile.name,
            retired_username=retired_username,
            retired_email=retired_email,
            current_state=pending,
            last_state=pending,
            responses='Created in state {} by create_retirement'.format(pending)
        )

    def update_state(self, update):
        """
        Perform the necessary checks for a state change and update the state and response if passed
        or throw a RetirementStateError with a useful error message
        """
        self._validate_update_data(update)
        self._validate_state_update(update['new_state'])

        old_state = self.current_state
        self.current_state = RetirementState.objects.get(state_name=update['new_state'])
        self.last_state = old_state
        self.responses += "\n Moved from {} to {}:\n{}\n".format(old_state, self.current_state, update['response'])
        self.save()

    @classmethod
    def get_retirement_for_retirement_action(cls, username):
        """
        Convenience method to get a UseRetirementStatus for a particular user with some checking
        to make sure they're in a state that is acceptable to be acted upon. The user should be
        in a "working state" (not a dead end state, PENDING, or *_COMPLETE). This should help
        a bit with situations like the retirement driver accidentally trying to act upon the
        same user twice at the same time, or trying to take action on an errored user.

        Can raise UserRetirementStatus.DoesNotExist or RetirementStateError, otherwise should
        return a UserRetirementStatus
        """
        retirement = cls.objects.get(original_username=username)
        state = retirement.current_state

        if state.required or state.state_name.endswith('_COMPLETE'):
            raise RetirementStateError('{} is in {}, not a valid state to perform retirement '
                                       'actions on.'.format(retirement, state.state_name))

        return retirement

    def __unicode__(self):
        return u'User: {} State: {} Last Updated: {}'.format(self.user.id, self.current_state, self.modified)


@receiver(models.signals.post_delete, sender=UserRetirementStatus)
def remove_pending_retirement_request(sender, instance, **kwargs):   # pylint: disable=unused-argument
    """
    Whenever a UserRetirementStatus record is deleted, remove the user's UserRetirementRequest record
    IFF the UserRetirementStatus record was still PENDING.
    """
    pending_state = RetirementState.objects.filter(state_name='PENDING')[0]
    if pending_state and instance.current_state == pending_state:
        UserRetirementRequest.objects.filter(user=instance.user).delete()
