"""
A test suite for Edraak's customization on the Courses API
"""
import json
import ddt
from django.conf import settings
from django.core.urlresolvers import reverse
from django.test import TestCase
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory
from mock import patch

from course_api.tests.helpers import mock_requests_get
from course_api.views import CourseDetailView
from course_api import serializers
from course_api import helpers


MARKETING_COURSE_FIXTURE = {
    'effort': '3',
    'name': 'A Fancier edX Demo Course',
    'name_en': 'An English Fancier edX Demo Course',
    'name_ar': 'An Arabic Fancier edX Demo Course',
    'course_image': 'https://edx.org/image.png',
    'course_video': 'https://edx.org/image.mp4',
    'short_description': 'This is the course where you learn everything!',
    'short_description_en': 'English description of the course where you learn everything!',
    'short_description_ar': 'Arabic description of the course where you learn everything!',
    'overview': """
        <div>
          <h1>Course Overview</h1>
          <p>An overview form the marketing site</p>
        </div>
    """,
}

MARKETING_COURSE_FIXTURE_MISSING_IMAGE = {
    # The marketing site sometimes reports null video and completely missing image!
    key: (None if key == 'course_video' else value)
    for key, value in MARKETING_COURSE_FIXTURE.iteritems()
    if key != 'course_image'
}


@ddt.ddt
class HelpersTestCase(ModuleStoreTestCase):
    def test_default_settings(self):
        self.assertFalse(settings.FEATURES.get('EDRAAK_USE_MARKETING_COURSE_DETAILS_API'),
                         msg='The feature should be off by default, even during testing.')

    def test_feature_by_default_helper(self):
        self.assertFalse(helpers.is_marketing_api_enabled(), 'Should be disabled by default')

    @ddt.unpack
    @ddt.data(
        {
            # Reason: Marketing site is disabled
            'mktg_urls': {'ROOT': 'https://omar', 'COURSE_DETAILS_API_FORMAT': '/api/{course_id}/'},
            'features': {'ENABLE_MKTG_SITE': False},
            'error_regexp': '.*MARKETING.*ENABLE_MKTG_SITE.*',
        },
        {
            # Reason: Missing course details api format configuration
            'mktg_urls': {'ROOT': 'https://omar'},
            'features': {'ENABLE_MKTG_SITE': True},
            'error_regexp': '.*MARKETING.*COURSE_DETAILS_API_FORMAT.*',
        },
        {
            # Reason: Missing MKTG_URL['ROOT']
            'mktg_urls': {'COURSE_DETAILS_API_FORMAT': '/api/{course_id}/'},
            'features': {'ENABLE_MKTG_SITE': True},
            'error_regexp': '.*MARKETING.*ROOT.*',
        },
        {
            # Reason: Missing `course_id` in the API.
            'mktg_urls': {'ROOT': 'https://omar', 'COURSE_DETAILS_API_FORMAT': '/api/{course_key}/'},
            'features': {'ENABLE_MKTG_SITE': True},
            'error_regexp': '.*MARKETING.*course_id.*',
        },
    )
    @patch.dict(settings.FEATURES, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=True)
    def test_enabled_feature_but_invalid_configs(self, mktg_urls, features, error_regexp):
        with patch.dict(settings.FEATURES, features):
            with patch.object(settings, 'MKTG_URLS', mktg_urls):
                with self.assertRaisesRegexp(Exception, error_regexp):
                    helpers.is_marketing_api_enabled()

    @patch.dict(settings.FEATURES, ENABLE_MKTG_SITE=True, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=True)
    @patch.object(settings, 'MKTG_URLS', {
        'ROOT': 'https://dummy-marketing.com',
        'COURSE_DETAILS_API_FORMAT': '/api/marketing/courses/{course_id}',
    })
    def test_enabled_feature_and_marketing(self):
        self.assertTrue(helpers.is_marketing_api_enabled(), 'Should be enabled')


@ddt.ddt
@patch.dict(settings.FEATURES, ENABLE_MKTG_SITE=True, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=True)
@patch.object(settings, 'MKTG_URLS', {
    'ROOT': 'https://dummy-marketing.com',
    'COURSE_DETAILS_API_FORMAT': '/api/marketing/courses/{course_id}',
})
class GetMarketingDataHelperTestCase(TestCase):
    @ddt.data('MITX/CS101/2010', 'course-v1:edX+Demo+2014')
    def test_language_header_and_url(self, course_key):
        expected_url = 'https://dummy-marketing.com/api/marketing/courses/{}'.format(course_key)

        with mock_requests_get() as mocked_get:
            helpers.get_marketing_data(course_key, 'eo')
            self.assertEquals(mocked_get.call_count, 1)  # Should be called once
            mocked_get.assert_called_once_with(
                url=expected_url,
                headers={'Accept-Language': 'eo'},
                timeout=4
            )

    def test_valid_response(self):
        with mock_requests_get(status_code=200, body_json={'name': 'My Course'}):
            course = helpers.get_marketing_data('course-v1:edX+Demo+2014', 'ar')
            self.assertIsInstance(course, dict)  # Sanity check: Should return a dictionary
            self.assertDictEqual(course, {'name': 'My Course'})  # Should return the JSON provided by the marketing API

    def assertCourseNotFoundWarning(self):
        with mock_requests_get(status_code=404, body_json={'name': 'My Course'}):
            course = helpers.get_marketing_data('course-v1:edX+Demo+2014', 'ar')
            self.assertFalse(course)  # Should return nothing!

    @patch('course_api.helpers.log.warning')
    def test_course_found_no_warning(self, warning):
        with mock_requests_get(status_code=200, body_json={'name': 'My Course'}):
            course = helpers.get_marketing_data('course-v1:edX+Demo+2014', 'ar')
            self.assertTrue(course)  # Should return nothing!
            self.assertEquals(0, warning.call_count)  # Should NOT log a warning!

    def test_invalid_response_actual_log(self):
        self.assertCourseNotFoundWarning()

    @patch('course_api.helpers.log.warning')
    def test_invalid_response_mocked_log(self, warning):
        self.assertCourseNotFoundWarning()
        self.assertEquals(1, warning.call_count)  # Should log a warning!


@ddt.ddt
@patch.dict(settings.FEATURES, ENABLE_MKTG_SITE=True, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=True)
@patch.object(settings, 'MKTG_URLS', {
    'ROOT': 'https://dummy-marketing.com',
    'COURSE_DETAILS_API_FORMAT': '/api/marketing/courses/{course_id}',
})
class MarketingSiteCourseDetailsTestCase(ModuleStoreTestCase):
    def setUp(self):
        super(MarketingSiteCourseDetailsTestCase, self).setUp()
        self.course = CourseFactory.create(
            display_name='edx demo course',
            effort='3',
            short_description='forgot to add it in LMS!',
        )
        self.view = CourseDetailView(course_id=unicode(self.course.id))
        self.course_api_url = reverse('course-detail', args=[self.course.id])

    @patch.dict(settings.FEATURES, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=False)
    def test_default_serializer_class(self):
        """
        Ensure that the default serializer works when the feature is disabled.
        """
        self.assertIs(self.view.get_serializer_class(), serializers.CourseDetailSerializer)

    @patch.dict(settings.FEATURES, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=True)
    def test_edraak_serializer_class(self):
        self.assertIs(self.view.get_serializer_class(), serializers.CourseDetailMarketingSerializer)

    @patch.dict(settings.FEATURES, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=False)
    def test_no_marketing_overrides(self):
        res = self.client.get(self.course_api_url)

        self.assertContains(res, 'edx demo course')
        self.assertNotContains(res, '<p>An overview form the marketing site</p>')

    def _test_with_marketing_overrides(self, short_description):
        res = self.client.get(self.course_api_url)

        self.assertNotContains(res, 'edx demo course')
        self.assertContains(res, 'A Fancier edX Demo Course')
        self.assertContains(res, 'An English Fancier edX Demo Course')
        self.assertContains(res, 'An Arabic Fancier edX Demo Course')
        self.assertContains(res, '<p>An overview form the marketing site</p>')
        
        self.assertContains(res, short_description)

        api_json = json.loads(res.content)
        self.assertIn(api_json['effort'], '3')

    @patch.dict(settings.FEATURES, EDRAAK_USE_MARKETING_COURSE_DETAILS_API=True)
    @ddt.data(MARKETING_COURSE_FIXTURE, MARKETING_COURSE_FIXTURE_MISSING_IMAGE)
    def test_with_marketing_overrides(self, course_fixture):
        with mock_requests_get(body_json=course_fixture):
            with patch('course_api.serializers.get_language', return_value='en'):
                self._test_with_marketing_overrides('English description of the course where you learn everything!')

            with patch('course_api.serializers.get_language', return_value='ar'):
                self._test_with_marketing_overrides('Arabic description of the course where you learn everything!')
