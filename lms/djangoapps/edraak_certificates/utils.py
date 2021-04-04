import json
import logging
import requests
from rest_framework.status import HTTP_200_OK
import urllib
from urlparse import urljoin

from courseware.courses import get_course_about_section
from edraak_certificates.generator import EdraakCertificate
from edraak_certificates.ace_override import send_with_file
from edx_ace.recipient import Recipient
from django.conf import settings
from django.core.cache import cache
import os
import re

from courseware.access import has_access
from lms.djangoapps.courseware.views.views import is_course_passed
from opaque_keys.edx import locator
from xmodule.modulestore.django import modulestore
from openedx.core.djangoapps.ace_common.template_context import get_base_template_context
from openedx.core.djangoapps.safe_sessions.middleware import SafeCookieData
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from student.message_types import EdraakCertificateCongrats

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
    return cert


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
    cache_key_format='edraak_certificates.utils.is_student_pass.{0.id}.{1.id}',
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


def get_quoted_url(url):
    url = url
    last_slash = url.rfind('/')
    if last_slash > 1:
        return '{}{}'.format(url[:last_slash + 1], urllib.quote(url[last_slash + 1:]))
    else:
        return urllib.quote(url)


def get_recommended_courses(request, language):
    result = []
    url = settings.PROGS_URLS.get('RECOMMENDER_URL', None) or None
    cookies = request.COOKIES.copy()
    if url:
        response = requests.get(
            url=url,
            params={'size': 3},
            timeout=15,
            cookies=cookies
        )
        if response.status_code == HTTP_200_OK:
            data = json.loads(response.content)
            added_params = settings.EDRAAK_UTM_PARAMS_CERTIFICATE_EMAIL
            for info in data:
                course_url = urljoin(info['course_url'], added_params) if added_params else info['course_url']
                result.append({
                    'course_url': course_url,
                    'course_img': get_quoted_url(info['course_image'].encode('utf-8')),
                    'course_name': info['name_{language}'.format(language=language)],
                })
        else:
            raise ValueError('Response no OK: {status}'.format(status=response.status_code))
    return result


def send_certificate_by_email(site, request, course_key):
    try:
        cert = generate_certificate(request=request, course_id=str(course_key))
        language = 'en' if cert.is_english else 'ar'
        recommended_courses = []
        user = request.user
        try:
            recommended_courses = get_recommended_courses(request=request, language=language)
        except Exception as rec_error:  # pylint: disable=broad-except
            logger.error('Recommender error while generating certificate email for user {username}: {error_msg}'.format(
                username=user.username,
                error_msg='{exception_type}: {msg}'.format(
                    exception_type=type(rec_error).__name__,
                    msg=str(rec_error) or '',
                ),
            ))
        else:
            if len(recommended_courses) == 0:
                logger.warning(
                    'Recommender returned empty list in certificate email for user {username}'.format(
                        username=user.username,
                    ))

        message_context = get_base_template_context(site)
        message_context.update({
            'from_address': configuration_helpers.get_value('email_from_address', settings.DEFAULT_FROM_EMAIL),
            'recommendations': recommended_courses,
            'recommendations_width': int(100 / len(recommended_courses)) if recommended_courses else 0,
            'course_name': cert.course_name
        })
        msg = EdraakCertificateCongrats().personalize(
            recipient=Recipient(user.username, user.email),
            language=language,
            user_context=message_context,
        )
        pdf_file = cert.temp_file

        send_with_file(msg, 'Certificate of Completion.pdf', pdf_file.read(), 'application/pdf')
    except Exception as e:  # pylint: disable=broad-except
        logger.error('Sending certificate by email failed: {error_msg}'.format(error_msg=str(e)))
