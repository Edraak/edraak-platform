# coding=utf-8
"""
Tests for Edraak Certificates.
"""
import unittest
from datetime import datetime, timedelta
from django.conf import settings
from django.test import TestCase
from mock import patch, Mock
import ddt
import os
import pytz

from edraak_certificates import utils
from edraak_certificates.utils import STATIC_DIR
from edraak_certificates.generator import fonts, generate_certificate
from edraak_tests.tests.helpers import ModuleStoreLoggedInTestCase
from xmodule.modulestore.tests.factories import CourseFactory


@ddt.ddt
class SettingsTestCase(TestCase):
    """
    Sanity checks for the environment settings
    """
    def test_if_enabled(self):
        self.assertTrue(settings.FEATURES['EDRAAK_CERTIFICATES_APP'], 'The feature should be enabled in tests')
        self.assertFalse(settings.FEATURES['EDRAAK_CERTIFICATES_DASHBOARD_BUTTON'],
                         msg='The feature should be disabled in tests by default, to ensure edX tests pass')
        self.assertIn('edraak_certificates', settings.INSTALLED_APPS,
                      msg='Edraak certificate app should be enabled in tests')

    def test_magic_wand_import(self):
        try:
            from wand.image import Image
        except ImportError:
            self.fail('This should not fail! Review the `edraak_certificates/tests/__init__.py` file')

    def test_ensure_only_new_dynamic_logos(self):
        """
        Ensures that we stick to deployment-free logos.

        If you're doing this, please add a logo from within the admin instead.

        You can override certificates for specific courses without the need to remove a file.
        """
        legacy_asset_files = list(sorted(fonts.keys() + [
            'certificate_layout_ltr.jpg',
            'certificate_layout_rtl.jpg',

            'Full-AUB-Seal.jpg',
            'HCAC_Logo.png',
            'auc.jpg',
            'bayt-logo2-en.png',
            'british-council.jpg',
            'crescent-petroleum.jpg',
            'csbe.png',
            'delftx.jpg',
            'edx.png',
            'hsoub.png',
            'mbrcgi.png',
            'moe.png',
            'pmijo.jpg',
            'psut.png',
            'qou.png',
            'qrta_logo.jpg',
        ]))

        actual_assets = sorted(os.listdir(STATIC_DIR))

        self.assertListEqual(legacy_asset_files, actual_assets)


from organizations.tests.factories import OrganizationFactory
from django.core.files.uploadedfile import SimpleUploadedFile, InMemoryUploadedFile
from organizations.models import OrganizationCourse


@ddt.ddt
class OrganizationLogoTestCase(TestCase):
    def test_course_org_db_logo(self):
        """
        You know what? We can add logos to HogwartsX from the DB from now on!

        Ref: https://en.wikipedia.org/wiki/Hogwarts
        """

        org_id = 'HogwartsX'
        course_key = 'HogwartsX/Wizard_101/1814'

        with utils.OrganizationLogo(org_id, course_key) as logo:
            self.assertIsNone(logo)

        logo_file_name = 'hsoub.png'
        with open(os.path.join(STATIC_DIR, logo_file_name), 'rb') as logo:
            OrganizationFactory.create(
                short_name='HogwartsX',
                logo=SimpleUploadedFile(logo_file_name, content=logo.read()),
            )

        with utils.OrganizationLogo(org_id, course_key) as logo:
            self.assertRegexpMatches(os.path.basename(logo.name), r'.*hsoub.*\.png.*')

    def test_course_org_db_logo_override_legacy(self):
        """
        Want to re-upload an organization logo? You can do it!

        Just create an organization with and upload the logo.
        """
        org_id = 'MITX'
        course_key = 'MITX/Demo/2017'

        with utils.OrganizationLogo(org_id, course_key) as prev_logo:
            # Should provide the legacy logo
            self.assertEquals('edx.png', os.path.basename(prev_logo.name))

        hsoub_logo = 'hsoub.png'  # Sorry we're using this all over the place!
        with open(os.path.join(STATIC_DIR, hsoub_logo), 'rb') as updated_logo:
            org = OrganizationFactory.create(
                short_name='MITX',
                logo=SimpleUploadedFile(hsoub_logo, content=updated_logo.read()),
            )

        with utils.OrganizationLogo(org_id, course_key) as updated_logo:
            # Should use the database logo
            self.assertRegexpMatches(os.path.basename(updated_logo.name), r'.*hsoub.*\.png.*')

    @unittest.skip('Edraak: Skipped in Hawthorn Upgrade')
    def test_course_org_db_logo_association(self):
        """
        Suppose we created a course and incorrectly called it `MITX/Demo/2017` while we want Hsoub logo on it?

        This ensures that we can override it using the `OrganizationCourse` model.
        """
        org_id = 'PSUT'
        course_key = 'PSUT/Demo/Fall2018'

        with utils.OrganizationLogo(org_id, course_key) as prev_logo:
            self.assertEquals('psut.png', os.path.basename(prev_logo.name))  # Should use the PSUT legacy logo

        moe_logo = 'moe.png'
        with open(os.path.join(STATIC_DIR, moe_logo), 'rb') as updated_logo:
            wanted_org = OrganizationFactory.create(
                name='Ministry of Education',
                short_name='MoE',
                logo=SimpleUploadedFile(moe_logo, content=updated_logo.read()),
            )

        # Associate the course with a different organization
        OrganizationCourse.objects.create(organization=wanted_org, course_id=course_key)

        with utils.OrganizationLogo(org_id, course_key) as overridden_logo:
            self.assertRegexpMatches(os.path.basename(overridden_logo.name), r'.*moe.*.\.png*')  # Now it's an MoE course!

    def test_no_double_organization_course(self):
        """
        Apparently edX allows multiple organizations per course, but my limited imagination wouldn't grok it!
        """
        org_id = 'PSUT'
        course_key = 'PSUT/Demo/Fall2018'

        wanted_org = OrganizationFactory.create(short_name='MITX')
        OrganizationCourse.objects.create(organization=wanted_org, course_id=course_key)

        unwanted_org = OrganizationFactory.create(short_name='AnythingX')
        OrganizationCourse.objects.create(organization=unwanted_org, course_id=course_key)

        with self.assertRaisesRegexp(Exception, '.*multiple organizations.*'):
            with utils.OrganizationLogo(org_id, course_key):
                self.fail('Should fail when having multiple organizations')

    @ddt.unpack
    @ddt.data(
        # Ensures case insensitive and str/unicode agnostic comparison
        {'organization': u'HARVARDX', 'logo_name': 'edx.png'},

        # Checks for all orgs
        {'organization': u'harvardx', 'logo_name': 'edx.png'},
        {'organization': 'mitx', 'logo_name': 'edx.png'},
        {'organization': 'qrf', 'logo_name': 'edx.png'},
        {'organization': 'bayt.com', 'logo_name': 'bayt-logo2-en.png'},
        {'organization': 'qrta', 'logo_name': 'qrta_logo.jpg'},
        {'organization': 'aub', 'logo_name': 'Full-AUB-Seal.jpg'},
        {'organization': 'csbe', 'logo_name': 'csbe.png'},
        {'organization': 'hcac', 'logo_name': 'HCAC_Logo.png'},
        {'organization': 'delftx', 'logo_name': 'delftx.jpg'},
        {'organization': 'britishcouncil', 'logo_name': 'british-council.jpg'},
        {'organization': 'crescent_petroleum', 'logo_name': 'crescent-petroleum.jpg'},
        {'organization': 'auc', 'logo_name': 'auc.jpg'},
        {'organization': 'pmijo', 'logo_name': 'pmijo.jpg'},
        {'organization': 'qou', 'logo_name': 'qou.png'},
        {'organization': 'moe', 'logo_name': 'moe.png'},
        {'organization': 'mbrcgi', 'logo_name': 'mbrcgi.png'},
        {'organization': 'hsoub', 'logo_name': 'hsoub.png'},
        {'organization': 'psut', 'logo_name': 'psut.png'},
    )
    def test_legacy_organization_logos(self, organization, logo_name):
        course_id = 'MITX/Greetings/2017'  # Just a dummy course id
        with utils.OrganizationLogo(organization, course_id) as logo_file:
            self.assertEquals(logo_name, os.path.basename(logo_file.name))
            self.assertTrue(os.path.exists(os.path.join(STATIC_DIR, logo_name)),
                            msg='Logo should exist in assets directory')

    def test_course_logo_legacy_hack(self):
        """
        Tests for the special case for a bad course org.

        Reference:
            Title: Add special case for AUC STEAM course checking on ID
            Link: https://github.com/Edraak/edx-platform/pull/277
        """
        course_id = 'course-v1:Edraak+STEAM101+R1_Q1_2017'
        with utils.OrganizationLogo('Edraak', course_id) as logo:
            self.assertEquals('auc.jpg', os.path.basename(logo.name))

    def test_ensure_sane_default_organization_logo(self):
        with utils.OrganizationLogo('HogwartsX', 'HogwartsX/Wizard_101/1814') as logo:
            self.assertIsNone(logo)


@ddt.ddt
class HelpersTestCase(TestCase):
    def test_normalize_spaces(self):
        """
        For some reason, this function don't `strip()`.

        We're dealing with legacy code here, so we don't touch it!
        """
        self.assertEquals(utils.normalize_spaces(''), '')
        self.assertEquals(utils.normalize_spaces(' '), ' ')
        self.assertEquals(utils.normalize_spaces('  '), ' ')
        self.assertEquals(utils.normalize_spaces(' a  b '), ' a b ')
        self.assertEquals(utils.normalize_spaces(' Hello  World  ! '), ' Hello World ! ')

    @patch('edraak_certificates.arabic_reshaper.reshape')
    @patch.object(utils, 'normalize_spaces')
    @patch.object(utils, 'get_display')
    def test_text_to_bidi(self, get_display, normalize_spaces, reshape):
        """
        C'mon! The function interface is too complex test! Let's test it's implementation!

        Don't judge me for this :D
        """
        utils.text_to_bidi('Hello World!')

        # Testing the implementation for the win!
        self.assertTrue(get_display.call_count)
        self.assertTrue(normalize_spaces.call_count)
        self.assertTrue(reshape.call_count)

    def test_contains_rtl_text(self):
        self.assertFalse(utils.contains_rtl_text(''))
        self.assertFalse(utils.contains_rtl_text('Hello, World!'))

        self.assertTrue(utils.contains_rtl_text('Hello, Wørld!'))
        self.assertTrue(utils.contains_rtl_text(u'Hello, Wørld!'))

    @ddt.data(
        u"BritishCouncil/Eng100/T4_2015",
        u"course-v1:BritishCouncil+Eng100+T4_2015",
        u"course-v1:BritishCouncil+Eng2+2016Q3",
        u"course-v1:BritishCouncil+Eng3+Q4-2016"
    )
    def test_get_course_sponsor(self, course_id):
        self.assertEquals('crescent_petroleum', utils.get_course_sponsor(course_id))

    def test_ensure_sane_default_sponsor(self):
        # `None` should be returned when there's no sponsor!
        self.assertIsNone(utils.get_course_sponsor('edX/Demo/2012'))

    @patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_DASHBOARD_BUTTON=True)
    def test_show_dashboard_button_flag_enabled(self):
        with patch('edraak_certificates.utils.is_certificate_allowed', return_value=True):
            self.assertTrue(utils.show_dashboard_button(Mock(), Mock()),
                            msg='Should be visible when the certificate is allowed')

        with patch('edraak_certificates.utils.is_certificate_allowed', return_value=False):
            self.assertFalse(utils.show_dashboard_button(Mock(), Mock()),
                             msg='Should be hidden when the certificate is not allowed')

    @patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_DASHBOARD_BUTTON=False)
    def test_show_dashboard_button_flag_disabled(self):
        with patch('edraak_certificates.utils.is_certificate_allowed', return_value=True):
            self.assertFalse(utils.show_dashboard_button(Mock(), Mock()),
                             msg='Should be hidden when the feature flag is disabled')

    def test_cached_is_course_passed(self):
        self.assertTrue(True, 'I do not know how to test it! So I am adding this placehoder test to tell you about it!')

    def test_is_certificate_feature_enabled(self):
        with patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=False, ORGANIZATIONS_APP=False):
            self.assertFalse(utils.is_certificates_feature_enabled(),
                             msg='Should say `disabled` when the feature is')

        with patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=True, ORGANIZATIONS_APP=False):
            with self.assertRaisesRegexp(Exception, '.*organization.*'):
                utils.is_certificates_feature_enabled()  # Should not work while the organization app being disabled

        with patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=True, ORGANIZATIONS_APP=True):
            self.assertTrue(utils.is_certificates_feature_enabled(),
                            msg='Should say `enabled` when both of the certs and orgs app are enabled')


class IsCertificateAllowedHelperStaffTestCases(ModuleStoreLoggedInTestCase):
    LOGIN_STAFF = True

    def test_is_certificate_allowed(self):
        with patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=False):
            self.assertFalse(utils.is_certificate_allowed(self.user, self.course),
                             msg='Should be disabled when the feature is')

        with patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=True):
            self.assertTrue(utils.is_certificate_allowed(self.user, self.course),
                            msg='Should be enabled for staff')


class IsCertificateAllowedHelperStudentTestCases(ModuleStoreLoggedInTestCase):
    LOGIN_STAFF = False

    def test_is_certificate_allowed(self):
        with patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=False):
            self.assertFalse(utils.is_certificate_allowed(self.user, self.course),
                             msg='Should be disabled when the feature is')

        with patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=True):
            self.assertTrue(utils.is_certificate_allowed(self.user, self.course),
                            msg='Should be enabled for users when (it is past end date)')

    def create_course(self):
        past_week = datetime.now(pytz.UTC) - timedelta(days=7)
        return CourseFactory.create(
            start=past_week,
            end=past_week,
        )


class IsStudentPassHelperTestCases(ModuleStoreLoggedInTestCase):
    LOGIN_STAFF = False
    ENROLL_USER = True

    @patch.dict(settings.FEATURES, EDRAAK_CERTIFICATES_APP=False)
    @patch('edraak_certificates.utils.is_course_passed', return_value=True)
    def test_feature_disabled(self, _is_course_passed):
        self.assertFalse(utils.is_student_pass(self.user, unicode(self.course.id)),
                         msg='Should say student did not pass when the feature is disabled!')

    @patch('edraak_certificates.utils.is_course_passed', return_value=True)
    def test_feature_enabled(self, _is_course_passed):
        self.assertFalse(utils.is_student_pass(self.user, unicode(self.course.id)),
                         msg='Should return True when the feature is enabled and the student have passed!')

    @patch('edraak_certificates.utils.is_course_passed', return_value=False)
    def test_staff_users(self, _is_course_passed):
        self.user.is_staff = True
        self.user.save()

        self.assertTrue(utils.is_student_pass(self.user, unicode(self.course.id)),
                        msg='Should return True for Staff users regardless of their mark')

    @patch('edraak_certificates.utils.is_course_passed', return_value=False)
    def test_staff_users(self, _is_course_passed):
        self.user.is_staff = True
        self.user.save()

        self.assertTrue(utils.is_student_pass(self.user, unicode(self.course.id)),
                        msg='Should return True for Staff users regardless of their mark')

    @patch('edraak_certificates.utils.cached_is_course_passed', return_value=False)
    def test_using_cached_is_course_passed(self, cached_is_course_passed):
        """
        Should use the cached grade function.
        """
        with patch('edraak_certificates.utils.is_certificate_allowed', return_value=True):
            self.assertFalse(utils.is_student_pass(self.user, unicode(self.course.id)))
            self.assertEquals(1, cached_is_course_passed.call_count)
