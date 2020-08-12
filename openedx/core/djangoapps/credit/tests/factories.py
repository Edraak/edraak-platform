# pylint:disable=missing-docstring
import datetime
import json
import uuid

from django.contrib.auth.models import User
import factory
from factory.fuzzy import FuzzyText
import pytz

from openedx.core.djangoapps.credit.models import (
    CreditProvider,
    CreditEligibility,
    CreditCourse,
    CreditRequest,
    CreditRequirement,
    CreditRequirementStatus,
)
from util.date_utils import to_timestamp


class CreditCourseFactory(factory.DjangoModelFactory):
    class Meta(object):
        model = CreditCourse

    course_key = FuzzyText(prefix='fake.org/', suffix='/fake.run')
    enabled = True


class CreditRequirementFactory(factory.DjangoModelFactory):
    class Meta(object):
        model = CreditRequirement

    course = factory.SubFactory(CreditCourseFactory)


class CreditRequirementStatusFactory(factory.DjangoModelFactory):
    class Meta(object):
        model = CreditRequirementStatus

    requirement = factory.SubFactory(CreditRequirementFactory)
    status = CreditRequirementStatus.REQUIREMENT_STATUS_CHOICES[0][0]


class CreditProviderFactory(factory.DjangoModelFactory):
    class Meta(object):
        model = CreditProvider

    provider_id = FuzzyText(length=5)
    provider_url = FuzzyText(prefix='http://')


class CreditEligibilityFactory(factory.DjangoModelFactory):
    class Meta(object):
        model = CreditEligibility

    course = factory.SubFactory(CreditCourseFactory)


class CreditRequestFactory(factory.DjangoModelFactory):
    class Meta(object):
        model = CreditRequest

    uuid = factory.LazyAttribute(lambda o: uuid.uuid4().hex)  # pylint: disable=undefined-variable

    # pylint: disable=access-member-before-definition,attribute-defined-outside-init,no-self-argument,unused-argument
    @factory.post_generation
    def post(obj, create, extracted, **kwargs):
        """
        Post-generation handler.

        Sets up parameters field.
        """
        if not obj.parameters:
            course_key = obj.course.course_key
            user = User.objects.get(username=obj.username)
            user_profile = user.profile

            obj.parameters = json.dumps({
                "request_uuid": obj.uuid,
                "timestamp": to_timestamp(datetime.datetime.now(pytz.UTC)),
                "course_org": course_key.org,
                "course_num": course_key.course,
                "course_run": course_key.run,
                "final_grade": '0.96',
                "user_username": user.username,
                "user_email": user.email,
                "user_full_name": user_profile.name,
                "user_mailing_address": "",
                "user_country": user_profile.country.code or "",
            })

        obj.save()
