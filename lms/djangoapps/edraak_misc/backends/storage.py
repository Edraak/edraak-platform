"""
GoogleCloudStorage using media_url
"""
from django.conf import settings
from storages.backends.gcloud import GoogleCloudStorage
from urlparse import urljoin

class GoogleCloudMediaStorage(GoogleCloudStorage):
    """GoogleCloudStorage suitable for Django's Media files."""

    def url(self, name):
        """.url that doesn't call Google."""
        return urljoin(settings.MEDIA_URL, name)
