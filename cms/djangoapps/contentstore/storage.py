"""
Storage backend for course import and export.
"""
from __future__ import absolute_import

from django.conf import settings
from django.core.files.storage import get_storage_class
from storages.backends.s3boto import S3BotoStorage
from storages.utils import setting


class ImportExportS3Storage(S3BotoStorage):  # pylint: disable=abstract-method
    """
    S3 backend for course import and export OLX files.
    """

    def __init__(self):
        bucket = setting('COURSE_IMPORT_EXPORT_BUCKET', settings.AWS_STORAGE_BUCKET_NAME)
        super(ImportExportS3Storage, self).__init__(bucket=bucket, custom_domain=None, querystring_auth=True)


def get_course_import_export_storage():
    """
    Configures and returns a django Storage instance that can be used
    to store course export import tgz files.

    This class is Edraak-specific to work with GCloud and any other provider.
    """
    config = settings.COURSE_IMPORT_EXPORT_BACKEND
    if config:
        storage_class = get_storage_class(config['class'])
        return storage_class(**config['options'])

    # Backward compatibility if `COURSE_IMPORT_EXPORT_BACKEND` is not configured.
    return get_storage_class(settings.COURSE_IMPORT_EXPORT_STORAGE)()
