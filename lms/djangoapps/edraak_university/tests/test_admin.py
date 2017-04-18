"""
Tests for the University ID admin.
"""

from mock import Mock, patch

from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from edraak_university.models import UniversityID
from edraak_university.admin import UniversityIDAdmin


class UniversityIDAdminTest(ModuleStoreTestCase):
    """
    Tests for correct HTML handling in the UniversityID admin.
    """

    LOGIN_STAFF = True

    def setUp(self):
        super(UniversityIDAdminTest, self).setUp()

        self.admin = UniversityIDAdmin(UniversityID, Mock())

    def test_allow_html_tags(self):
        self.assertTrue(self.admin.edraak_user.allow_tags, 'Should allow HTML in the user field, link tag is needed')
        self.assertFalse(hasattr(self.admin.email, 'allow_tags'), 'Should not allow HTML the email field')

    def test_assert_escaping(self):
        uni_id_mock = Mock(
            user=Mock(
                pk='<b>PK</b>',
                __unicode__=lambda _: u'Hello <b>World</b>',
            ),
        )

        # Patch `reverse` function to return the primary key as-is to test the escaping
        with patch('edraak_university.admin.reverse', side_effect=lambda url, args: args[0]):
            user_html = unicode(self.admin.edraak_user(uni_id_mock))

        self.assertIn('<a', user_html, 'Should contain a link')
        self.assertNotIn('<b>', user_html, 'Should escape the username')
        self.assertEquals(2, user_html.count('&lt;b&gt;'), 'Should escape all the content tags')
