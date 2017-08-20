# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('edraak_university', '0002_university_id_setting'),
    ]

    operations = [
        migrations.AddField(
            model_name='universityid',
            name='can_edit',
            field=models.BooleanField(default=True),
        ),
    ]
