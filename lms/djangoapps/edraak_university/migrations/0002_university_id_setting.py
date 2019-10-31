# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import opaque_keys.edx.django.models


class Migration(migrations.Migration):

    dependencies = [
        ('course_groups', '0001_initial'),
        ('edraak_university', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='UniversityIDSettings',
            fields=[
                ('course_key', opaque_keys.edx.django.models.UsageKeyField(max_length=255, serialize=False, primary_key=True, db_index=True)),
                ('registration_end_date', models.DateField(null=True, verbose_name='Registration End Date', blank=True)),
                ('terms_and_conditions', models.TextField(null=True, verbose_name='Terms and Conditions', blank=True)),
            ],
        ),
        migrations.AddField(
            model_name='universityid',
            name='cohort',
            field=models.ForeignKey(to='course_groups.CourseUserGroup', null=True),
        ),
        migrations.AlterField(
            model_name='universityid',
            name='section_number',
            field=models.CharField(max_length=10, verbose_name='Section Number'),
        ),
        migrations.AlterField(
            model_name='universityid',
            name='university_id',
            field=models.CharField(max_length=100, verbose_name='Student University ID'),
        ),
    ]
