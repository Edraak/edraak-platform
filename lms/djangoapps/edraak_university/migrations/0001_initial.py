# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone
from django.conf import settings
import opaque_keys.edx.django.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='UniversityID',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('course_key', opaque_keys.edx.django.models.UsageKeyField(max_length=255, db_index=True)),
                ('university_id', models.CharField(max_length=100, verbose_name='Student University ID')),
                ('section_number', models.CharField(max_length=10, verbose_name='Section Number')),
                ('date_created', models.DateTimeField(default=django.utils.timezone.now)),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='universityid',
            unique_together=set([('user', 'course_key')]),
        ),
    ]
