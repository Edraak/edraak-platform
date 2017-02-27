# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('student', '0006_logoutviewconfiguration'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='gender',
            field=models.CharField(blank=True, max_length=6, null=True, db_index=True, choices=[(b'm', b'Male'), (b'f', b'Female')]),
        ),
    ]
