import logging

from courseware.courses import get_course_about_section
from opaque_keys.edx import locator
from xmodule.modulestore.django import modulestore
from .edraakcertificate import EdraakCertificate
from bidi.algorithm import get_display
from django.conf import settings
from django.core.cache import cache
import os
import re

from courseware.access import has_access
from lms.djangoapps.courseware.views.views import is_course_passed
from opaque_keys.edx import locator
from xmodule.modulestore.django import modulestore

logger = logging.getLogger(__name__)


def generate_certificate(request, course_id):
    course_key = locator.CourseLocator.from_string(course_id)

    path_builder = request.build_absolute_uri
    course = modulestore().get_course(course_key)
    course_short_desc = get_course_about_section(
        request, course, 'short_description')

    preview_mode = request.GET.get('preview', None)
    cert = EdraakCertificate(course=course,
                             user=request.user,
                             course_desc=course_short_desc,
                             preview_mode=preview_mode,
                             path_builder=path_builder)

    cert.generate_and_save()
    return cert.temp_file


STATIC_DIR = os.path.join(os.path.dirname(__file__), 'assets')


def cached_function(cache_key_format, timeout=30):
    """
    Decorator to cache heavy functions.
    Use it as the following:
    @cached_function("module.add_numbers.{0}.{1}", 30)
    def add_numbers(a, b):
        return a + b
    """
    def the_decorator(func):

        def cached_func(*args, **kwargs):
            cache_key = cache_key_format.format(*args, **kwargs)
            cached_result = cache.get(cache_key)

            if cached_result is not None:
                return cached_result
            else:
                result = func(*args, **kwargs)
                cache.set(cache_key, result, timeout)
                return result

        return cached_func

    return the_decorator


def is_certificates_feature_enabled():
    if not settings.FEATURES.get('EDRAAK_CERTIFICATES_APP'):
        return False

    if not settings.FEATURES.get('ORGANIZATIONS_APP'):
        raise Exception(
            'You have enabled the `edraak_certificates` (`EDRAAK_CERTIFICATES_APP`) app without enabling the '
            'organizations app. Please enable the latter with the `ORGANIZATIONS_APP` feature flag.'
        )

    return True


def is_certificate_allowed(user, course):
    if not is_certificates_feature_enabled():
        return False

    if has_access(user, 'staff', course.id):
        return True

    return course.may_certify()


@cached_function(
    cache_key_format='.utils.is_student_pass.{0.id}.{1.id}',
    timeout=60 * 5,  # Cache up to 5 minutes
)
def cached_is_course_passed(user, course):
    return is_course_passed(course=course, student=user)


def is_student_pass(user, course_id):
    course_key = locator.CourseLocator.from_string(course_id)
    course = modulestore().get_course(course_key)

    if not is_certificate_allowed(user, course):
        return False

    # Skip grading for course staff
    if has_access(user, 'staff', course):
        return True

    return cached_is_course_passed(user, course)


def show_dashboard_button(user, course):
    if not settings.FEATURES.get('EDRAAK_CERTIFICATES_DASHBOARD_BUTTON'):
        return False

    return is_certificate_allowed(user, course)


def _get_legacy_organization_logo(organization, course_id):
    organization = organization.lower()
    if organization == 'mitx' or organization == 'harvardx' or organization == 'qrf':
        return 'edx.png'
    elif organization == u'bayt.com':
        return 'bayt-logo2-en.png'
    elif organization == u'qrta':
        return 'qrta_logo.jpg'
    elif organization == 'aub':
        return 'Full-AUB-Seal.jpg'
    elif organization == "csbe":
        return 'csbe.png'
    elif organization == "hcac":
        return 'HCAC_Logo.png'
    elif organization == "delftx":
        return 'delftx.jpg'
    elif organization == "britishcouncil":
        return 'british-council.jpg'
    elif organization == "crescent_petroleum":
        return 'crescent-petroleum.jpg'
    elif organization == 'auc':
        return 'auc.jpg'
    elif organization == 'pmijo':
        return 'pmijo.jpg'
    elif organization == 'qou':
        return 'qou.png'
    elif organization == 'moe':
        return 'moe.png'
    elif organization == 'mbrcgi':
        return 'mbrcgi.png'
    elif organization == 'hsoub':
        return 'hsoub.png'
    elif organization == 'psut':
        return 'psut.png'
    elif course_id == 'course-v1:Edraak+STEAM101+R1_Q1_2017':
        return 'auc.jpg'
    else:
        return None


def _get_organization_logo_from_db(organization_name, course_id):
    from organizations.models import Organization, OrganizationCourse

    course_orgs = OrganizationCourse.objects.filter(course_id=course_id)

    if len(course_orgs) == 0:
        try:
            course_org = Organization.objects.get(short_name__iexact=organization_name)
            return course_org.logo
        except Organization.DoesNotExist:
            return

    if len(course_orgs) == 1:
        course_org = course_orgs[0]
        return course_org.organization.logo

    raise Exception('The course `{}` has multiple organizations, the edraak certificate app is confused!')


class OrganizationLogo(object):
    _legacy_logo_file = None

    def __init__(self, organization, course_id):
        self.organization = organization
        self.course_id = course_id

        self._database_logo_file = _get_organization_logo_from_db(organization, course_id)

        if not self._database_logo_file:
            self.legacy_logo_name = _get_legacy_organization_logo(self.organization, self.course_id)

    def __enter__(self):
        if self._database_logo_file:
            return self._database_logo_file

        if self.legacy_logo_name:
            self._legacy_logo_file = open(os.path.join(STATIC_DIR, self.legacy_logo_name), 'rb')
            return self._legacy_logo_file

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._database_logo_file:
            if self._legacy_logo_file:
                self._legacy_logo_file.close()


def get_course_sponsor(course_id):
    crescent_petroleum_sponsored_course_ids = (
        "BritishCouncil/Eng100/T4_2015",
        "course-v1:BritishCouncil+Eng100+T4_2015",
        "course-v1:BritishCouncil+Eng2+2016Q3",
        "course-v1:BritishCouncil+Eng3+Q4-2016"
    )

    if unicode(course_id) in crescent_petroleum_sponsored_course_ids:
        return "crescent_petroleum"

    return None


def normalize_spaces(text):
    return re.sub(' +', ' ', text)


def contains_rtl_text(string):
        try:
            string.decode('ascii')
        except (UnicodeDecodeError, UnicodeEncodeError) as e:
            return True
        else:
            return False
