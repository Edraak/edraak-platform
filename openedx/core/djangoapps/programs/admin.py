"""
django admin pages for program support models
"""
from config_models.admin import ConfigurationModelAdmin
from django.contrib import admin

from openedx.core.djangoapps.programs.models import ProgramsApiConfig


class ProgramsApiConfigAdmin(ConfigurationModelAdmin):
    pass


admin.site.register(ProgramsApiConfig, ProgramsApiConfigAdmin)
