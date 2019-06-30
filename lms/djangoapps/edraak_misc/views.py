from django.views.decorators.csrf import ensure_csrf_cookie
from django.conf import settings
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser

from edxmako.shortcuts import render_to_response

from util.json_request import JsonResponse
from util.cache import cache_if_anonymous

from courseware.courses import get_courses, sort_by_announcement
from .utils import is_student_pass, edraak_courses_logic


@transaction.non_atomic_requests
@login_required
def check_student_grades(request):
    user = request.user
    course_id = request.POST['course_id']

    return JsonResponse({
        'success': False,
        'error': is_student_pass(user, request, course_id)
    })


@transaction.non_atomic_requests
@login_required
def student_course_complete_status(request, course_id):
    """
    This view returns a json response describing if a user has
    completed (passed) a course.

    :param course_id: the id for the course to check
    """

    return JsonResponse({
        'complete': is_student_pass(request.user, request, course_id)
    })


@ensure_csrf_cookie
@cache_if_anonymous()
def all_courses(request, extra_context={}, user=AnonymousUser()):
    """
    Render the edX main page.

    extra_context is used to allow immediate display of certain modal windows, eg signup,
    as used by external_auth.
    """

    # The course selection work is done in courseware.courses.
    domain = settings.FEATURES.get('FORCE_UNIVERSITY_DOMAIN')  # normally False
    # do explicit check, because domain=None is valid
    if domain is False:
        domain = request.META.get('HTTP_HOST')

    # Hardcoded `AnonymousUser()` to hide unpublished courses always
    courses = get_courses(AnonymousUser(), domain=domain)
    courses = sort_by_announcement(courses)

    courses = edraak_courses_logic(courses)

    context = {'courses': courses}

    context.update(extra_context)
    return render_to_response('all_courses.html', context)
