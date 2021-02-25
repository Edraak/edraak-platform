import logging

import os

from django.http import HttpResponse
from django.shortcuts import redirect
from django.conf import settings
from django.core.urlresolvers import reverse
from wsgiref.util import FileWrapper
from django.contrib.auth.decorators import login_required
from django.db import transaction

from edxmako.shortcuts import render_to_response
from rest_framework.decorators import api_view
from rest_framework.response import Response
from xmodule.modulestore.django import modulestore

from opaque_keys.edx import locator

from certificates.api import \
    certificate_downloadable_status, generate_user_certificates
from lms.djangoapps.certificates.models import CertificateStatuses, \
    GeneratedCertificate, certificate_status_for_student
from certificates.views import render_cert_by_uuid

from .utils import generate_certificate
from .utils import is_student_pass, is_certificate_allowed
from courseware.access import has_access

logger = logging.getLogger(__name__)


@transaction.non_atomic_requests
@login_required
def issue(request, course_id):
    student = request.user

    # Extracts CourseLocator Object from course ID.
    course_key = locator.CourseLocator.from_string(course_id)
    # Extract the CourseOverview object of the course.
    course = modulestore().get_course(course_key)

    # Check the status of GeneratedCertificate in XQueue.
    certificate_status = \
        certificate_status_for_student(student, course.id)['status']

    # init with a fail, if it didn't match the conditions for issue.
    template = 'edraak_certificates/fail.html'

    # If user didn't issue or pass certificate, or an error happened
    # in the generation.
    if certificate_status in [CertificateStatuses.unavailable,
                              CertificateStatuses.notpassing,
                              CertificateStatuses.error]:
        # If the course is certifiable and the user has passed it.
        if is_certificate_allowed(student, course) and \
                is_student_pass(student, course_id):

            forced_grade = None
            if has_access(student, 'staff', course):
                forced_grade = "Pass"

            # generate the certificate
            generate_user_certificates(student, course.id,
                                       course=course, forced_grade=forced_grade, request=request)
            template = 'edraak_certificates/issue.html'

    elif certificate_status == CertificateStatuses.downloadable:
        cert = GeneratedCertificate.objects.get(
            user_id=student.id,
            course_id=course_key,
            status=CertificateStatuses.downloadable
        )
        return render_cert_by_uuid(request, cert.verify_uuid)

    return render_to_response(template, {
        'course_id': course_id,
        'user': student,
        'cert_course': course,
        'is_staff': has_access(student, 'staff', course),
        'studio_url': settings.CMS_BASE
    })


@transaction.non_atomic_requests
@api_view()
def check_status(request, course_id):
    course_key = locator.CourseLocator.from_string(course_id)
    status = certificate_downloadable_status(request.user, course_key)
    return Response(status)


@transaction.non_atomic_requests
@login_required
def download(request, course_id):
    user = request.user
    # Extracts CourseLocator Object from course ID.
    course_key = locator.CourseLocator.from_string(course_id)
    # Extract the CourseOverview object of the course.
    course = modulestore().get_course(course_key)

    certificate_status = \
        certificate_status_for_student(user, course.id)['status']

    if certificate_status == CertificateStatuses.downloadable or is_student_pass(user, course_id):
        pdf_file = generate_certificate(request, course_id).temp_file
        file_size = os.path.getsize(pdf_file.name)
        wrapper = FileWrapper(pdf_file)
        # `application/octet-stream` is to force download
        response = HttpResponse(wrapper, content_type='application/octet-stream')
        response['Content-Length'] = file_size
        response['Content-Disposition'] = "attachment; filename=Edraak-Certificate.pdf"

        return response
    else:
        return redirect(reverse('dashboard'))
