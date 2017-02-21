import logging
import hmac
from urllib import urlencode
from hashlib import sha256
from collections import defaultdict
from datetime import datetime, timedelta

from django_countries import countries
from opaque_keys.edx.keys import CourseKey

from django.utils.translation import ugettext as _
from django.core.urlresolvers import reverse
from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from django.core.validators import validate_email


from opaque_keys import InvalidKeyError
from courseware.courses import get_course_by_id

from student.models import UserProfile


DATE_TIME_FORMAT = '%Y-%m-%dT%H:%M:%S'


log = logging.getLogger(__name__)


ordered_hmac_keys = (
    'course_id',
    'email',
    'name',
    'enrollment_action',
    'country',
    'level_of_education',
    'gender',
    'year_of_birth',
    'lang',
    'time',
)


def is_enabled_language(lang):
    return lang in dict(settings.LANGUAGES)


def forus_error_redirect(*messages):
    message = '. '.join(messages) + '.'

    url = '{base_url}?{params}'.format(
        base_url=reverse('forus_v1_message'),
        params=urlencode({
            'message': message.encode('utf-8')
        })
    )

    return HttpResponseRedirect(url)


def calculate_hmac(msg_to_hash):
    secret_key = settings.FORUS_AUTH_SECRET_KEY
    dig = hmac.new(secret_key.encode('utf-8'), msg_to_hash.encode('utf-8'), digestmod=sha256)
    return dig.hexdigest()


def validate_forus_hmac(params):
    remote_hmac = params.get('forus_hmac')

    if not remote_hmac:
        log.warn('HMAC is missing for email=`%s`', params.get('email'))

        raise ValidationError({
            "forus_hmac": [_("The security check has failed on the provided parameters")]
        })

    params_pairs = [
        u'{}={}'.format(key, params.get(key, ''))
        for key in ordered_hmac_keys
    ]

    msg_to_hash = u';'.join(params_pairs)
    local_hmac = calculate_hmac(msg_to_hash)

    if local_hmac != remote_hmac:
        log.warn(
            'HMAC is not correct remote=`%s` != local=`%s`. msg_to_hash=`%s`',
            remote_hmac,
            local_hmac,
            msg_to_hash,
        )

        raise ValidationError({
            "forus_hmac": [_("The security check has failed on the provided parameters")]
        })


def validate_forus_params_values(params):
    errors = defaultdict(lambda: [])

    def mark_as_invalid(field, field_label):
        # Translators: This is for the ForUs API
        errors[field].append(_('Invalid {field_label} has been provided').format(
            field_label=field_label,
        ))

    try:
        validate_email(params.get('email'))

        try:
            user = User.objects.get(email=params.get('email'))

            if user.is_staff or user.is_superuser:
                errors['email'].append(_("ForUs profile cannot be created for admins and staff."))
        except User.DoesNotExist:
            pass
    except ValidationError:
        # Translators: This is for the ForUs API
        errors['email'].append(_("The provided email format is invalid"))

    if len(params.get('name', '')) <= 2:
        # Translators: This is for the ForUs API
        mark_as_invalid('name', _('name'))

    if params.get('gender') not in dict(UserProfile.GENDER_CHOICES):
        # Translators: This is for the ForUs API
        mark_as_invalid('gender', _('gender'))

    if not is_enabled_language(params.get('lang')):
        # Translators: This is for the ForUs API
        mark_as_invalid('lang', _('language'))

    if not params.get('country') or params.get('country') not in dict(countries):
        # Translators: This is for the ForUs API
        mark_as_invalid('country', _('country'))

    if params.get('level_of_education') not in dict(UserProfile.LEVEL_OF_EDUCATION_CHOICES):
        # Translators: This is for the ForUs API
        mark_as_invalid('level_of_education', _('level of education'))

    try:
        course_key = CourseKey.from_string(params['course_id'])
        course = get_course_by_id(course_key)

        if not course.is_self_paced():
            if not course.enrollment_has_started():

                # Translators: This is for the ForUs API
                errors['course_id'].append(_('The course has not yet been opened for enrollment, '
                                             'please go back to the ForUs portal and enroll in other courses'))

            if course.enrollment_has_ended():
                # Translators: This is for the ForUs API
                errors['course_id'].append(_('Enrollment for this course has been closed, '
                                             'please go back to the ForUs portal and enroll in other courses'))

    except InvalidKeyError:
        log.warning(
            u"User {username} tried to {action} with invalid course id: {course_id}".format(
                username=params.get('username'),
                action=params.get('enrollment_action'),
                course_id=params.get('course_id'),
            )
        )

        mark_as_invalid('course_id', _('course id'))
    except Http404:
        # Translators: This is for the ForUs API
        errors['course_id'].append(_('The requested course does not exist'))

    try:
        if int(params['year_of_birth']) not in UserProfile.VALID_YEARS:
            # Translators: This is for the ForUs API
            mark_as_invalid('year_of_birth', _('birth year'))
    except ValueError:
        # Translators: This is for the ForUs API
        mark_as_invalid('year_of_birth', _('birth year'))

    try:
        time = datetime.strptime(params.get('time'), DATE_TIME_FORMAT)
        now = datetime.utcnow()

        if time > now:
            # Translators: This is for the ForUs API
            errors['time'].append(_('future date has been provided'))

        if time < (now - timedelta(days=1)):
            # Translators: This is for the ForUs API
            errors['time'].append(_('Request has expired'))

    except ValueError:
        # Translators: This is for the ForUs API
        mark_as_invalid('time', _('date format'))

    if len(errors):
        raise ValidationError(errors)


def validate_forus_params(params):
    validate_forus_hmac(params)
    validate_forus_params_values(params)

    clean_params = {
        key: params[key]
        for key in ordered_hmac_keys
    }

    clean_params['forus_hmac'] = params['forus_hmac']

    return clean_params


def setfuncattr(name, value):
    def inner(func):
        setattr(func, name, value)
        return func

    return inner
