from __future__ import print_function

from django.core.management.base import BaseCommand
from django.db import connection, migrations
from django.db.utils import OperationalError
from student.models import UserProfile


def check_name_en():
    """
    Check whether (name_en) exists or not. This is helpful when migrating (devstack) data, and for data that is
    already migrated

    :return: (True) if the field exists, (False) otherwise
    """
    result = True

    # To avoid writing (DB-Engine Dependent) query to check for the column, we will
    # apply a simple SELECT statement that will fail when the column is not present
    verified = UserProfile.objects.raw('SELECT id, name_en from auth_userprofile where id = 0;')
    try:
        for _ in verified:
            pass

    except OperationalError:
        result = False

    return result


class Command(BaseCommand):
    help = 'Migrate database column (auth_userprofile.name_en) into (auth_userprofile.meta) and drop the column'

    def handle(self, *args, **options):
        if check_name_en():
            print('Database column (name_en) found in (auth_userprofile) table. Applying migration...')

            old_data = UserProfile.objects.raw(
                "SELECT id, meta, name_en as db_name_en FROM auth_userprofile WHERE (name_en IS NOT NULL) AND (name_en != '');"
            )

            # Copying from (name_en) to (meta)
            for user_profile in old_data:
                user_profile.name_en = user_profile.db_name_en
                user_profile.save()

            # Dropping (name_en) from the table
            print('Data copied to (meta) field. Dropping old column (name_en)...')
            connection.cursor().execute("ALTER TABLE auth_userprofile DROP COLUMN name_en;")

            print('All done!')

        else:
            print('Database column (name_en) not found. Migration has been already applied!')
