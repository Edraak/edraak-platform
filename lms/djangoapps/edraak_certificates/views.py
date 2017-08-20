from django.contrib.auth.decorators import login_required
from django.core.files.temp import NamedTemporaryFile
from django.core.servers.basehttp import FileWrapper
from django.db import transaction
from django.http import HttpResponse, Http404
from wand.image import Image
import os

from edxmako.shortcuts import render_to_response
from opaque_keys.edx import locator
from xmodule.modulestore.django import modulestore

from edraak_certificates.generator import generate_certificate
from edraak_certificates.utils import is_student_pass


@login_required
def issue(request, course_id):
    return render_to_response('edraak_certificates/issue.html', {
        'course_id': course_id,
    })


@transaction.non_atomic_requests
@login_required
def preview(request, course_id):
    user = request.user

    course_key = locator.CourseLocator.from_string(course_id)
    course = modulestore().get_course(course_key)

    if is_student_pass(user, course_id):
        template = 'edraak_certificates/view.html'
    else:
        template = 'edraak_certificates/fail.html'

    return render_to_response(template, {
        'user': user,
        'cert_course': course,  # Course name is set to `cert_course` to avoid header design bug
    })


@transaction.non_atomic_requests
@login_required
def download_pdf(request, course_id):
    user = request.user

    course_key = locator.CourseLocator.from_string(course_id)
    course = modulestore().get_course(course_key)

    if not is_student_pass(user, course_id):
        raise Http404()

    pdf_file = generate_certificate(request, course)
    wrapper = FileWrapper(pdf_file)

    # `application/octet-stream` is to force download
    response = HttpResponse(wrapper, content_type='application/octet-stream')

    response['Content-Length'] = os.path.getsize(pdf_file.name)
    response['Content-Disposition'] = "attachment; filename=Edraak-Certificate.pdf"

    return response


@transaction.non_atomic_requests
@login_required
def preview_png(request, course_id):
    user = request.user

    course_key = locator.CourseLocator.from_string(course_id)
    course = modulestore().get_course(course_key)

    if not is_student_pass(user, course_id):
        raise Http404()

    pdf_file = generate_certificate(request, course)
    image_file = NamedTemporaryFile(suffix='-cert.png')

    with Image(filename=pdf_file.name) as img:
        with img.clone() as i:
            i.save(filename=image_file.name)

    wrapper = FileWrapper(image_file)
    response = HttpResponse(wrapper, content_type='image/png')
    response['Content-Length'] = os.path.getsize(image_file.name)

    return response
