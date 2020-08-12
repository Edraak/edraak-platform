"""
Test data created by CourseSerializer and CourseDetailSerializer
"""

from __future__ import unicode_literals

from datetime import datetime

import ddt
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from xblock.core import XBlock

from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.models.course_details import CourseDetails
from xmodule.course_module import DEFAULT_START_DATE
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import check_mongo_calls

from ..serializers import CourseDetailSerializer, CourseSerializer
from .mixins import CourseApiFactoryMixin


@ddt.ddt
class TestCourseSerializer(CourseApiFactoryMixin, ModuleStoreTestCase):
    """
    Test CourseSerializer
    """
    expected_mongo_calls = 0
    maxDiff = 5000  # long enough to show mismatched dicts, in case of error
    serializer_class = CourseSerializer
    shard = 3

    ENABLED_SIGNALS = ['course_published']

    def setUp(self):
        super(TestCourseSerializer, self).setUp()
        self.staff_user = self.create_user('staff', is_staff=True)
        self.honor_user = self.create_user('honor', is_staff=False)
        self.request_factory = APIRequestFactory()

        image_path = u'/c4x/edX/toy/asset/just_a_test.jpg'
        image_url = u'http://testserver' + image_path
        self.expected_data = {
            'id': u'edX/toy/2012_Fall',
            'name': u'Toy Course',
            'number': u'toy',
            'org': u'edX',
            'short_description': u'A course about toys.',
            'media': {
                'course_image': {
                    'uri': image_path,
                },
                'course_video': {
                    'uri': u'http://www.youtube.com/watch?v=test_youtube_id',
                },
                'image': {
                    'raw': image_url,
                    'small': image_url,
                    'large': image_url,
                }
            },
            'start': u'2015-07-17T12:00:00Z',
            'start_type': u'timestamp',
            'start_display': u'July 17, 2015',
            'end': u'2015-09-19T18:00:00Z',
            'enrollment_start': u'2015-06-15T00:00:00Z',
            'enrollment_end': u'2015-07-15T00:00:00Z',
            'blocks_url': u'http://testserver/api/courses/v1/blocks/?course_id=edX%2Ftoy%2F2012_Fall',
            'effort': u'6 hours',
            'pacing': 'instructor',
            'mobile_available': True,
            'hidden': False,
            'invitation_only': False,

            # 'course_id' is a deprecated field, please use 'id' instead.
            'course_id': u'edX/toy/2012_Fall',
            'duration': 9,
        }

    def _get_request(self, user=None):
        """
        Build a Request object for the specified user.
        """
        if user is None:
            user = self.honor_user
        request = Request(self.request_factory.get('/'))
        request.user = user
        return request

    def _get_result(self, course):
        """
        Return the CourseSerializer for the specified course.
        """
        course_overview = CourseOverview.get_from_id(course.id)
        return self.serializer_class(course_overview, context={'request': self._get_request()}).data

    def test_basic(self):
        course = self.create_course()
        CourseDetails.update_about_video(course, 'test_youtube_id', self.staff_user.id)
        with check_mongo_calls(self.expected_mongo_calls):
            result = self._get_result(course)
        self.assertDictEqual(result, self.expected_data)

    def test_hidden(self):
        course = self.create_course(
            course=u'custom',
            start=datetime(2015, 3, 15),
            catalog_visibility=u'none'
        )
        result = self._get_result(course)
        self.assertEqual(result['hidden'], True)

    def test_advertised_start(self):
        course = self.create_course(
            course=u'custom',
            start=datetime(2015, 3, 15),
            advertised_start=u'The Ides of March'
        )
        result = self._get_result(course)
        self.assertEqual(result['course_id'], u'edX/custom/2012_Fall')
        self.assertEqual(result['start_type'], u'string')
        self.assertEqual(result['start_display'], u'The Ides of March')

    def test_empty_start(self):
        course = self.create_course(start=DEFAULT_START_DATE, course=u'custom')
        result = self._get_result(course)
        self.assertEqual(result['course_id'], u'edX/custom/2012_Fall')
        self.assertEqual(result['start_type'], u'empty')
        self.assertIsNone(result['start_display'])

    @ddt.unpack
    @ddt.data(
        (True, 'self'),
        (False, 'instructor'),
    )
    def test_pacing(self, self_paced, expected_pacing):
        course = self.create_course(self_paced=self_paced)
        result = self._get_result(course)
        self.assertEqual(result['pacing'], expected_pacing)


class TestCourseDetailSerializer(TestCourseSerializer):
    """
    Test CourseDetailSerializer by rerunning all the tests
    in TestCourseSerializer, but with the
    CourseDetailSerializer serializer class.

    """
    # 1 mongo call is made to get the course About overview text.
    expected_mongo_calls = 1
    serializer_class = CourseDetailSerializer

    def setUp(self):
        super(TestCourseDetailSerializer, self).setUp()

        # update the expected_data to include the 'overview' data.
        about_descriptor = XBlock.load_class('about')
        overview_template = about_descriptor.get_template('overview.yaml')
        self.expected_data['overview'] = overview_template.get('data')
