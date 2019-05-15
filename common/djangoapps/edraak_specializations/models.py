from django.db import models


class CourseSpecializationInfo(models.Model):
    """
    Model for saving the specialization info of a course
    """
    course_id = models.CharField(max_length=255, db_index=True)
    specialization_slug = models.CharField(max_length=255)
    name_ar = models.CharField(max_length=255, blank=True)
    name_en = models.CharField(max_length=255, blank=True)
