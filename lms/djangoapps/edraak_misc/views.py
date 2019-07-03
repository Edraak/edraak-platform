from django.db import transaction
from django.contrib.auth.decorators import login_required

from util.json_request import JsonResponse

from edraak_certificates.utils import is_student_pass


@transaction.non_atomic_requests
@login_required
def check_student_grades(request, course_id):
    return JsonResponse({
        'success': False,
        'error': is_student_pass(request.user, course_id)
    })


@transaction.non_atomic_requests
@login_required
def course_complete_status(request, course_id):
    """
    This view returns a json response describing if a user has
    completed (passed) a course.

    :param course_id: the id for the course to check
    """

    return JsonResponse({
        'complete': is_student_pass(request.user, course_id)
    })
