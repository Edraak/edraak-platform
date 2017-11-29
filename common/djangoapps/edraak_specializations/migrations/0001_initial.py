# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CourseSpecializationInfo',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('course_id', models.CharField(max_length=255, db_index=True)),
                ('specialization_slug', models.CharField(max_length=255)),
                ('name_ar', models.CharField(max_length=255, blank=True)),
                ('name_en', models.CharField(max_length=255, blank=True)),
            ],
        ),
    ]
