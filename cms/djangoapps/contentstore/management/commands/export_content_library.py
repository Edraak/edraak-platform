"""
Script for exporting a content library from Mongo to a tar.gz file
"""
from __future__ import print_function
import os
import shutil

from django.core.management.base import BaseCommand, CommandError
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locator import LibraryLocator
from xmodule.modulestore.django import modulestore

from cms.djangoapps.contentstore import tasks


class Command(BaseCommand):
    """
    Export the specified content library into a directory.  Output will need to be tar zxcf'ed.
    """
    help = 'Export the specified content library into a directory'

    def add_arguments(self, parser):
        parser.add_argument('library_id')
        parser.add_argument('output_path', nargs='?')

    def handle(self, *args, **options):
        """
        Given a content library id, and an output_path folder.  Export the
        corresponding course from mongo and put it directly in the folder.
        """
        module_store = modulestore()
        try:
            library_key = CourseKey.from_string(options['library_id'])
        except InvalidKeyError:
            raise CommandError(u'Invalid library ID: "{0}".'.format(options['library_id']))
        if not isinstance(library_key, LibraryLocator):
            raise CommandError(u'Argument "{0}" is not a library key'.format(options['library_id']))

        library = module_store.get_library(library_key)
        if library is None:
            raise CommandError(u'Library "{0}" not found.'.format(options['library_id']))

        dest_path = options['output_path'] or '.'
        if not os.path.isdir(dest_path):
            raise CommandError(u'Output path "{0}" not found.'.format(dest_path))

        try:
            # Generate archive using the handy tasks implementation
            tarball = tasks.create_export_tarball(library, library_key, {}, None)
        except Exception as e:
            raise CommandError(u'Failed to export "{0}" with "{1}"'.format(library_key, e))
        else:
            with tarball:
                # Save generated archive with keyed filename
                prefix, suffix, n = str(library_key).replace(':', '+'), '.tar.gz', 0
                while os.path.exists(prefix + suffix):
                    n += 1
                    prefix = u'{0}_{1}'.format(prefix.rsplit('_', 1)[0], n) if n > 1 else u'{}_1'.format(prefix)
                filename = prefix + suffix
                target = os.path.join(dest_path, filename)
                tarball.file.seek(0)
                with open(target, 'w') as f:
                    shutil.copyfileobj(tarball.file, f)
                print(u'Library "{0}" exported to "{1}"'.format(library.location.library_key, target))
