# coding=utf-8
"""
Tests for digital signatures used to validate messages to/from credit providers.
"""

from django.test import TestCase
from django.test.utils import override_settings

from openedx.core.djangoapps.credit import signature


@override_settings(CREDIT_PROVIDER_SECRET_KEYS={
    "asu": u'abcd1234'
})
class SignatureTest(TestCase):
    """
    Tests for digital signatures.
    """
    shard = 2

    def test_unicode_secret_key(self):
        # Test a key that has type `unicode` but consists of ASCII characters
        # (This can happen, for example, when loading the key from a JSON configuration file)
        # When retrieving the shared secret, the type should be converted to `str`
        key = signature.get_shared_secret_key("asu")
        sig = signature.signature({}, key)
        self.assertEqual(sig, "7d70a26b834d9881cc14466eceac8d39188fc5ef5ffad9ab281a8327c2c0d093")

    @override_settings(CREDIT_PROVIDER_SECRET_KEYS={
        "asu": u'\u4567'
    })
    def test_non_ascii_unicode_secret_key(self):
        # Test a key that contains non-ASCII unicode characters
        # This should return `None` and log an error; the caller
        # is then responsible for logging the appropriate errors
        # so we can fix the misconfiguration.
        key = signature.get_shared_secret_key("asu")
        self.assertIs(key, None)

    def test_unicode_data(self):
        """ Verify the signature generation method supports Unicode data. """
        key = signature.get_shared_secret_key("asu")
        sig = signature.signature({'name': u'Ed Xavíer'}, key)
        self.assertEqual(sig, "76b6c9a657000829253d7c23977b35b34ad750c5681b524d7fdfb25cd5273cec")
