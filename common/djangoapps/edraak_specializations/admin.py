from django.contrib import admin

from .models import CourseSpecializationInfo


class SpecializationAdmin(admin.ModelAdmin):
    list_display = (
        'course_id',
        'name_ar',
        'name_en',
    )
    readonly_fields = ('name_ar', 'name_en',)

admin.site.register(CourseSpecializationInfo, SpecializationAdmin)
