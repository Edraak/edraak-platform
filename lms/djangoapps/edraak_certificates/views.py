from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, Http404
import StringIO

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

    pdf_string_io = generate_certificate(request, course)

    # `application/octet-stream` is to force download
    response = HttpResponse(pdf_string_io, content_type='application/octet-stream')
    response['Content-Length'] = len(pdf_string_io)
    response['Content-Disposition'] = "attachment; filename=Edraak-Certificate.pdf"

    return response


@transaction.non_atomic_requests
@login_required
def preview_png(request, course_id):
    from wand.image import Image  # Importing locally to avoid breaking tests.

    user = request.user

    course_key = locator.CourseLocator.from_string(course_id)
    course = modulestore().get_course(course_key)

    if not is_student_pass(user, course_id):
        raise Http404()

    pdf_file = generate_certificate(request, course)

    pdf_file_magic_wand = Image(file=pdf_file)
    image = pdf_file_magic_wand.clone()
    image.format = 'png'

    image_io = StringIO.StringIO()
    image.save(file=image_io)

    return HttpResponse(image_io, content_type='image/png')
