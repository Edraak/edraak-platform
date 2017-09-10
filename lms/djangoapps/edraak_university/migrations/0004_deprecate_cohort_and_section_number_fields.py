# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('edraak_university', '0003_universityid_can_edit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='universityid',
            name='cohort',
            field=models.IntegerField(null=True, db_column=b'cohort_id'),
        ),
        migrations.AlterField(
            model_name='universityid',
            name='section_number',
            field=models.CharField(default=b'', max_length=10, db_column=b'section_number', blank=True),
        ),
        migrations.RenameField(
            model_name='universityid',
            old_name='cohort',
            new_name='_cohort',
        ),
        migrations.RenameField(
            model_name='universityid',
            old_name='section_number',
            new_name='_section_number',
        ),
    ]
