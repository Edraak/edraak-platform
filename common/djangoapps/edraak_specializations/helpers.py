from urlparse import urljoin

from django.utils.translation import get_language
from django.conf import settings

from .models import CourseSpecializationInfo


def get_specialization_info(course_id):
    """
    Edraak (programs).
    This method is meant for returning a dictionary containing the
    information of a specialization a course is part of.

    :param course_id: the id of the course to check for a
    specialization.
    :return: a dictionary containing the specialization's name and
    title. ex:
    { "title" : "specialization title", "link": "http://www.exap..."}
    or an empty dictionary {} if the course is not part of a
    specialization
    """

    info = {}

    try:
        info_obj = CourseSpecializationInfo.objects.get(
            course_id=course_id)
    except CourseSpecializationInfo.DoesNotExist:
        return info

    info["title"] = info_obj.name_en if get_language() == "en"\
        else info_obj.name_ar
    info["link"] = urljoin(
        settings.PROGS_URLS.get('ROOT'),
        settings.PROGS_URLS.get("PROG_LMS", "").format(
            program_slug=info_obj.specialization_slug
        )
    )
    return info

