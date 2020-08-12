"""Certificates API

This is a Python API for generating certificates asynchronously.
Other Django apps should use the API functions defined in this module
rather than importing Django models directly.
"""
import logging

from django.conf import settings
from django.urls import reverse
from django.db.models import Q
from opaque_keys.edx.django.models import CourseKeyField
from opaque_keys.edx.keys import CourseKey

from branding import api as branding_api
from lms.djangoapps.certificates.models import (
    CertificateGenerationConfiguration,
    CertificateGenerationCourseSetting,
    CertificateInvalidation,
    CertificateStatuses,
    CertificateTemplate,
    CertificateTemplateAsset,
    ExampleCertificateSet,
    GeneratedCertificate,
    certificate_status_for_student
)
from lms.djangoapps.certificates.queue import XQueueCertInterface
from eventtracking import tracker
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from util.organizations_helpers import get_course_organization_id
from xmodule.modulestore.django import modulestore

log = logging.getLogger("edx.certificate")
MODES = GeneratedCertificate.MODES


def is_passing_status(cert_status):
    """
    Given the status of a certificate, return a boolean indicating whether
    the student passed the course.  This just proxies to the classmethod
    defined in models.py
    """
    return CertificateStatuses.is_passing_status(cert_status)


def format_certificate_for_user(username, cert):
    """
    Helper function to serialize an user certificate.

    Arguments:
        username (unicode): The identifier of the user.
        cert (GeneratedCertificate): a user certificate

    Returns: dict
    """
    try:
        return {
            "username": username,
            "course_key": cert.course_id,
            "type": cert.mode,
            "status": cert.status,
            "grade": cert.grade,
            "created": cert.created_date,
            "modified": cert.modified_date,
            "is_passing": is_passing_status(cert.status),

            # NOTE: the download URL is not currently being set for webview certificates.
            # In the future, we can update this to construct a URL to the webview certificate
            # for courses that have this feature enabled.
            "download_url": (
                cert.download_url or get_certificate_url(cert.user.id, cert.course_id)
                if cert.status == CertificateStatuses.downloadable
                else None
            ),
        }
    except CourseOverview.DoesNotExist:
        return None


def get_certificates_for_user(username):
    """
    Retrieve certificate information for a particular user.

    Arguments:
        username (unicode): The identifier of the user.

    Returns: list

    Example Usage:
    >>> get_certificates_for_user("bob")
    [
        {
            "username": "bob",
            "course_key": CourseLocator('edX', 'DemoX', 'Demo_Course', None, None),
            "type": "verified",
            "status": "downloadable",
            "download_url": "http://www.example.com/cert.pdf",
            "grade": "0.98",
            "created": 2015-07-31T00:00:00Z,
            "modified": 2015-07-31T00:00:00Z
        }
    ]

    """
    certs = []
    # Checks if certificates are not None before adding them to list
    for cert in GeneratedCertificate.eligible_certificates.filter(user__username=username).order_by("course_id"):
        formatted_cert = format_certificate_for_user(username, cert)
        if formatted_cert:
            certs.append(formatted_cert)
    return certs


def get_certificate_for_user(username, course_key):
    """
    Retrieve certificate information for a particular user for a specific course.

    Arguments:
        username (unicode): The identifier of the user.
        course_key (CourseKey): A Course Key.
    Returns: dict
    """
    try:
        cert = GeneratedCertificate.eligible_certificates.get(
            user__username=username,
            course_id=course_key
        )
    except GeneratedCertificate.DoesNotExist:
        return None
    return format_certificate_for_user(username, cert)


def generate_user_certificates(student, course_key, course=None, insecure=False, generation_mode='batch',
                               forced_grade=None):
    """
    It will add the add-cert request into the xqueue.

    A new record will be created to track the certificate
    generation task.  If an error occurs while adding the certificate
    to the queue, the task will have status 'error'. It also emits
    `edx.certificate.created` event for analytics.

    Args:
        student (User)
        course_key (CourseKey)

    Keyword Arguments:
        course (Course): Optionally provide the course object; if not provided
            it will be loaded.
        insecure - (Boolean)
        generation_mode - who has requested certificate generation. Its value should `batch`
        in case of django command and `self` if student initiated the request.
        forced_grade - a string indicating to replace grade parameter. if present grading
                       will be skipped.
    """
    xqueue = XQueueCertInterface()
    if insecure:
        xqueue.use_https = False

    if not course:
        course = modulestore().get_course(course_key, depth=0)

    generate_pdf = not has_html_certificates_enabled(course)

    cert = xqueue.add_cert(
        student,
        course_key,
        course=course,
        generate_pdf=generate_pdf,
        forced_grade=forced_grade
    )
    # If cert_status is not present in certificate valid_statuses (for example unverified) then
    # add_cert returns None and raises AttributeError while accesing cert attributes.
    if cert is None:
        return

    if CertificateStatuses.is_passing_status(cert.status):
        emit_certificate_event('created', student, course_key, course, {
            'user_id': student.id,
            'course_id': unicode(course_key),
            'certificate_id': cert.verify_uuid,
            'enrollment_mode': cert.mode,
            'generation_mode': generation_mode
        })
    return cert.status


def regenerate_user_certificates(student, course_key, course=None,
                                 forced_grade=None, template_file=None, insecure=False):
    """
    It will add the regen-cert request into the xqueue.

    A new record will be created to track the certificate
    generation task.  If an error occurs while adding the certificate
    to the queue, the task will have status 'error'.

    Args:
        student (User)
        course_key (CourseKey)

    Keyword Arguments:
        course (Course): Optionally provide the course object; if not provided
            it will be loaded.
        grade_value - The grade string, such as "Distinction"
        template_file - The template file used to render this certificate
        insecure - (Boolean)
    """
    xqueue = XQueueCertInterface()
    if insecure:
        xqueue.use_https = False

    if not course:
        course = modulestore().get_course(course_key, depth=0)

    generate_pdf = not has_html_certificates_enabled(course)
    log.info(
        "Started regenerating certificates for user %s in course %s with generate_pdf status: %s",
        student.username, unicode(course_key), generate_pdf
    )

    return xqueue.regen_cert(
        student,
        course_key,
        course=course,
        forced_grade=forced_grade,
        template_file=template_file,
        generate_pdf=generate_pdf
    )


def certificate_downloadable_status(student, course_key):
    """
    Check the student existing certificates against a given course.
    if status is not generating and not downloadable or error then user can view the generate button.

    Args:
        student (user object): logged-in user
        course_key (CourseKey): ID associated with the course

    Returns:
        Dict containing student passed status also download url, uuid for cert if available
    """
    current_status = certificate_status_for_student(student, course_key)

    # If the certificate status is an error user should view that status is "generating".
    # On the back-end, need to monitor those errors and re-submit the task.

    response_data = {
        'is_downloadable': False,
        'is_generating': True if current_status['status'] in [CertificateStatuses.generating,
                                                              CertificateStatuses.error] else False,
        'is_unverified': True if current_status['status'] == CertificateStatuses.unverified else False,
        'download_url': None,
        'uuid': None,
    }
    may_view_certificate = CourseOverview.get_from_id(course_key).may_certify()

    if current_status['status'] == CertificateStatuses.downloadable and may_view_certificate:
        response_data['is_downloadable'] = True
        response_data['download_url'] = current_status['download_url'] or get_certificate_url(student.id, course_key)
        response_data['uuid'] = current_status['uuid']

    return response_data


def set_cert_generation_enabled(course_key, is_enabled):
    """Enable or disable self-generated certificates for a course.

    There are two "switches" that control whether self-generated certificates
    are enabled for a course:

    1) Whether the self-generated certificates feature is enabled.
    2) Whether self-generated certificates have been enabled for this particular course.

    The second flag should be enabled *only* when someone has successfully
    generated example certificates for the course.  This helps avoid
    configuration errors (for example, not having a template configured
    for the course installed on the workers).  The UI for the instructor
    dashboard enforces this constraint.

    Arguments:
        course_key (CourseKey): The course identifier.

    Keyword Arguments:
        is_enabled (boolean): If provided, enable/disable self-generated
            certificates for this course.

    """
    CertificateGenerationCourseSetting.set_self_generatation_enabled_for_course(course_key, is_enabled)
    cert_event_type = 'enabled' if is_enabled else 'disabled'
    event_name = '.'.join(['edx', 'certificate', 'generation', cert_event_type])
    tracker.emit(event_name, {
        'course_id': unicode(course_key),
    })
    if is_enabled:
        log.info(u"Enabled self-generated certificates for course '%s'.", unicode(course_key))
    else:
        log.info(u"Disabled self-generated certificates for course '%s'.", unicode(course_key))


def is_certificate_invalid(student, course_key):
    """Check that whether the student in the course has been invalidated
    for receiving certificates.

    Arguments:
        student (user object): logged-in user
        course_key (CourseKey): The course identifier.

    Returns:
        Boolean denoting whether the student in the course is invalidated
        to receive certificates
    """
    is_invalid = False
    certificate = GeneratedCertificate.certificate_for_student(student, course_key)
    if certificate is not None:
        is_invalid = CertificateInvalidation.has_certificate_invalidation(student, course_key)

    return is_invalid


def cert_generation_enabled(course_key):
    """Check whether certificate generation is enabled for a course.

    There are two "switches" that control whether self-generated certificates
    are enabled for a course:

    1) Whether the self-generated certificates feature is enabled.
    2) Whether self-generated certificates have been enabled for this particular course.

    Certificates are enabled for a course only when both switches
    are set to True.

    Arguments:
        course_key (CourseKey): The course identifier.

    Returns:
        boolean: Whether self-generated certificates are enabled
            for the course.

    """
    return (
        CertificateGenerationConfiguration.current().enabled and
        CertificateGenerationCourseSetting.is_self_generation_enabled_for_course(course_key)
    )


def generate_example_certificates(course_key):
    """Generate example certificates for a course.

    Example certificates are used to validate that certificates
    are configured correctly for the course.  Staff members can
    view the example certificates before enabling
    the self-generated certificates button for students.

    Several example certificates may be generated for a course.
    For example, if a course offers both verified and honor certificates,
    examples of both types of certificate will be generated.

    If an error occurs while starting the certificate generation
    job, the errors will be recorded in the database and
    can be retrieved using `example_certificate_status()`.

    Arguments:
        course_key (CourseKey): The course identifier.

    Returns:
        None

    """
    xqueue = XQueueCertInterface()
    for cert in ExampleCertificateSet.create_example_set(course_key):
        xqueue.add_example_cert(cert)


def example_certificates_status(course_key):
    """Check the status of example certificates for a course.

    This will check the *latest* example certificate task.
    This is generally what we care about in terms of enabling/disabling
    self-generated certificates for a course.

    Arguments:
        course_key (CourseKey): The course identifier.

    Returns:
        list

    Example Usage:

        >>> from lms.djangoapps.certificates import api as certs_api
        >>> certs_api.example_certificate_status(course_key)
        [
            {
                'description': 'honor',
                'status': 'success',
                'download_url': 'http://www.example.com/abcd/honor_cert.pdf'
            },
            {
                'description': 'verified',
                'status': 'error',
                'error_reason': 'No template found!'
            }
        ]

    """
    return ExampleCertificateSet.latest_status(course_key)


def _safe_course_key(course_key):
    if not isinstance(course_key, CourseKey):
        return CourseKey.from_string(course_key)
    return course_key


def _course_from_key(course_key):
    return CourseOverview.get_from_id(_safe_course_key(course_key))


def _certificate_html_url(user_id, course_id, uuid):
    if uuid:
        return reverse('certificates:render_cert_by_uuid', kwargs={'certificate_uuid': uuid})
    elif user_id and course_id:
        kwargs = {"user_id": str(user_id), "course_id": unicode(course_id)}
        return reverse('certificates:html_view', kwargs=kwargs)
    return ''


def _certificate_download_url(user_id, course_id):
    try:
        user_certificate = GeneratedCertificate.eligible_certificates.get(
            user=user_id,
            course_id=_safe_course_key(course_id)
        )
        return user_certificate.download_url
    except GeneratedCertificate.DoesNotExist:
        log.critical(
            'Unable to lookup certificate\n'
            'user id: %d\n'
            'course: %s', user_id, unicode(course_id)
        )
    return ''


def has_html_certificates_enabled(course):
    if not settings.FEATURES.get('CERTIFICATES_HTML_VIEW', False):
        return False
    return course.cert_html_view_enabled


def get_certificate_url(user_id=None, course_id=None, uuid=None):
    url = ''

    course = _course_from_key(course_id)
    if not course:
        return url

    if has_html_certificates_enabled(course):
        url = _certificate_html_url(user_id, course_id, uuid)
    else:
        url = _certificate_download_url(user_id, course_id)
    return url


def get_active_web_certificate(course, is_preview_mode=None):
    """
    Retrieves the active web certificate configuration for the specified course
    """
    certificates = getattr(course, 'certificates', {})
    configurations = certificates.get('certificates', [])
    for config in configurations:
        if config.get('is_active') or is_preview_mode:
            return config
    return None


def get_certificate_template(course_key, mode, language):
    """
    Retrieves the custom certificate template based on course_key, mode, and language.
    """
    template = None
    # fetch organization of the course
    org_id = get_course_organization_id(course_key)

    # only consider active templates
    active_templates = CertificateTemplate.objects.filter(is_active=True)

    if org_id and mode:  # get template by org, mode, and key
        org_mode_and_key_templates = active_templates.filter(
            organization_id=org_id,
            mode=mode,
            course_key=course_key
        )
        template = get_language_specific_template_or_default(language, org_mode_and_key_templates)

    # since no template matched that course_key, only consider templates with empty course_key
    empty_course_key_templates = active_templates.filter(course_key=CourseKeyField.Empty)
    if not template and org_id and mode:  # get template by org and mode
        org_and_mode_templates = empty_course_key_templates.filter(
            organization_id=org_id,
            mode=mode
        )
        template = get_language_specific_template_or_default(language, org_and_mode_templates)
    if not template and org_id:  # get template by only org
        org_templates = empty_course_key_templates.filter(
            organization_id=org_id,
            mode=None
        )
        template = get_language_specific_template_or_default(language, org_templates)
    if not template and mode:  # get template by only mode
        mode_templates = empty_course_key_templates.filter(
            organization_id=None,
            mode=mode
        )
        template = get_language_specific_template_or_default(language, mode_templates)
    return template if template else None


def get_language_specific_template_or_default(language, templates):
    """
    Returns templates that match passed in language.
    Returns default templates If no language matches, or language passed is None
    """
    two_letter_language = _get_two_letter_language_code(language)
    language_or_default_templates = list(templates.filter(Q(language=two_letter_language) | Q(language=None) | Q(language='')))
    language_specific_template = get_language_specific_template(two_letter_language, language_or_default_templates)
    if language_specific_template:
        return language_specific_template
    else:
        return get_all_languages_or_default_template(language_or_default_templates)


def get_language_specific_template(language, templates):
    for template in templates:
        if template.language == language:
            return template
    return None


def get_all_languages_or_default_template(templates):
    for template in templates:
        if template.language == '':
            return template

    return templates[0] if templates else None


def _get_two_letter_language_code(language_code):
    """
    Shortens language to only first two characters (e.g. es-419 becomes es)
    This is needed because Catalog returns locale language which is not always a 2 letter code.
    """
    if language_code is None:
        return None
    elif language_code == '':
        return ''
    else:
        return language_code[:2]


def emit_certificate_event(event_name, user, course_id, course=None, event_data=None):
    """
    Emits certificate event.
    """
    event_name = '.'.join(['edx', 'certificate', event_name])
    if course is None:
        course = modulestore().get_course(course_id, depth=0)
    context = {
        'org_id': course.org,
        'course_id': unicode(course_id)
    }
    data = {
        'user_id': user.id,
        'course_id': unicode(course_id),
        'certificate_url': get_certificate_url(user.id, course_id)
    }
    event_data = event_data or {}
    event_data.update(data)

    with tracker.get_tracker().context(event_name, context):
        tracker.emit(event_name, event_data)


def get_asset_url_by_slug(asset_slug):
    """
    Returns certificate template asset url for given asset_slug.
    """
    asset_url = ''
    try:
        template_asset = CertificateTemplateAsset.objects.get(asset_slug=asset_slug)
        asset_url = template_asset.asset.url
    except CertificateTemplateAsset.DoesNotExist:
        pass
    return asset_url


def get_certificate_header_context(is_secure=True):
    """
    Return data to be used in Certificate Header,
    data returned should be customized according to the site configuration.
    """
    data = dict(
        logo_src=branding_api.get_logo_url(is_secure),
        logo_url=branding_api.get_base_url(is_secure),
    )

    return data


def get_certificate_footer_context():
    """
    Return data to be used in Certificate Footer,
    data returned should be customized according to the site configuration.
    """
    data = dict()

    # get Terms of Service and Honor Code page url
    terms_of_service_and_honor_code = branding_api.get_tos_and_honor_code_url()
    if terms_of_service_and_honor_code != branding_api.EMPTY_URL:
        data.update({'company_tos_url': terms_of_service_and_honor_code})

    # get Privacy Policy page url
    privacy_policy = branding_api.get_privacy_url()
    if privacy_policy != branding_api.EMPTY_URL:
        data.update({'company_privacy_url': privacy_policy})

    # get About page url
    about = branding_api.get_about_url()
    if about != branding_api.EMPTY_URL:
        data.update({'company_about_url': about})

    return data
