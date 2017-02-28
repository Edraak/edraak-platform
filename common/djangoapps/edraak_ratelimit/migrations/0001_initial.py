# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RateLimitedIP',
            fields=[
                ('ip_address', models.GenericIPAddressField(serialize=False, primary_key=True)),
                ('lockout_count', models.IntegerField(default=1, db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_index=True)),
                ('latest_user', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                'verbose_name': 'IP-based Lock',
                'verbose_name_plural': 'IP-based Locks',
            },
        ),
    ]
