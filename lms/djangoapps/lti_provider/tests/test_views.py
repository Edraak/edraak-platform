"""
Tests for the LTI provider views
"""

from django.urls import reverse
from django.test import TestCase
from django.test.client import RequestFactory
from mock import MagicMock, patch
from opaque_keys.edx.locator import BlockUsageLocator, CourseLocator

from courseware.testutils import RenderXBlockTestMixin
from lti_provider import models, views
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

LTI_DEFAULT_PARAMS = {
    'roles': u'Instructor,urn:lti:instrole:ims/lis/Administrator',
    'context_id': u'lti_launch_context_id',
    'oauth_version': u'1.0',
    'oauth_consumer_key': u'consumer_key',
    'oauth_signature': u'OAuth Signature',
    'oauth_signature_method': u'HMAC-SHA1',
    'oauth_timestamp': u'OAuth Timestamp',
    'oauth_nonce': u'OAuth Nonce',
    'user_id': u'LTI_User',
}

LTI_OPTIONAL_PARAMS = {
    'context_title': u'context title',
    'context_label': u'context label',
    'lis_result_sourcedid': u'result sourcedid',
    'lis_outcome_service_url': u'outcome service URL',
    'tool_consumer_instance_guid': u'consumer instance guid'
}

COURSE_KEY = CourseLocator(org='some_org', course='some_course', run='some_run')
USAGE_KEY = BlockUsageLocator(course_key=COURSE_KEY, block_type='problem', block_id='block_id')

COURSE_PARAMS = {
    'course_key': COURSE_KEY,
    'usage_key': USAGE_KEY
}


ALL_PARAMS = dict(LTI_DEFAULT_PARAMS.items() + COURSE_PARAMS.items())


def build_launch_request(extra_post_data=None, param_to_delete=None):
    """
    Helper method to create a new request object for the LTI launch.
    """
    if extra_post_data is None:
        extra_post_data = {}
    post_data = dict(LTI_DEFAULT_PARAMS.items() + extra_post_data.items())
    if param_to_delete:
        del post_data[param_to_delete]
    request = RequestFactory().post('/', data=post_data)
    request.user = UserFactory.create()
    request.session = {}
    return request


class LtiTestMixin(object):
    """
    Mixin for LTI tests
    """
    @patch.dict('django.conf.settings.FEATURES', {'ENABLE_LTI_PROVIDER': True})
    def setUp(self):
        super(LtiTestMixin, self).setUp()
        # Always accept the OAuth signature
        self.mock_verify = MagicMock(return_value=True)
        patcher = patch('lti_provider.signature_validator.SignatureValidator.verify', self.mock_verify)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.consumer = models.LtiConsumer(
            consumer_name='consumer',
            consumer_key=LTI_DEFAULT_PARAMS['oauth_consumer_key'],
            consumer_secret='secret'
        )
        self.consumer.save()


class LtiLaunchTest(LtiTestMixin, TestCase):
    """
    Tests for the lti_launch view
    """
    @patch('lti_provider.views.render_courseware')
    @patch('lti_provider.views.authenticate_lti_user')
    def test_valid_launch(self, _authenticate, render):
        """
        Verifies that the LTI launch succeeds when passed a valid request.
        """
        request = build_launch_request()
        views.lti_launch(request, unicode(COURSE_KEY), unicode(USAGE_KEY))
        render.assert_called_with(request, USAGE_KEY)

    @patch('lti_provider.views.render_courseware')
    @patch('lti_provider.views.store_outcome_parameters')
    @patch('lti_provider.views.authenticate_lti_user')
    def test_valid_launch_with_optional_params(self, _authenticate, store_params, _render):
        """
        Verifies that the LTI launch succeeds when passed a valid request.
        """
        request = build_launch_request(extra_post_data=LTI_OPTIONAL_PARAMS)
        views.lti_launch(request, unicode(COURSE_KEY), unicode(USAGE_KEY))
        store_params.assert_called_with(
            dict(ALL_PARAMS.items() + LTI_OPTIONAL_PARAMS.items()),
            request.user,
            self.consumer
        )

    @patch('lti_provider.views.render_courseware')
    @patch('lti_provider.views.store_outcome_parameters')
    @patch('lti_provider.views.authenticate_lti_user')
    def test_outcome_service_registered(self, _authenticate, store_params, _render):
        """
        Verifies that the LTI launch succeeds when passed a valid request.
        """
        request = build_launch_request()
        views.lti_launch(
            request,
            unicode(COURSE_PARAMS['course_key']),
            unicode(COURSE_PARAMS['usage_key'])
        )
        store_params.assert_called_with(ALL_PARAMS, request.user, self.consumer)

    def launch_with_missing_parameter(self, missing_param):
        """
        Helper method to remove a parameter from the LTI launch and call the view
        """
        request = build_launch_request(param_to_delete=missing_param)
        return views.lti_launch(request, None, None)

    def test_launch_with_missing_parameters(self):
        """
        Runs through all required LTI parameters and verifies that the lti_launch
        view returns Bad Request if any of them are missing.
        """
        for missing_param in views.REQUIRED_PARAMETERS:
            response = self.launch_with_missing_parameter(missing_param)
            self.assertEqual(
                response.status_code, 400,
                'Launch should fail when parameter ' + missing_param + ' is missing'
            )

    def test_launch_with_disabled_feature_flag(self):
        """
        Verifies that the LTI launch will fail if the ENABLE_LTI_PROVIDER flag
        is not set
        """
        with patch.dict('django.conf.settings.FEATURES', {'ENABLE_LTI_PROVIDER': False}):
            request = build_launch_request()
            response = views.lti_launch(request, None, None)
            self.assertEqual(response.status_code, 403)

    def test_forbidden_if_signature_fails(self):
        """
        Verifies that the view returns Forbidden if the LTI OAuth signature is
        incorrect.
        """
        self.mock_verify.return_value = False

        request = build_launch_request()
        response = views.lti_launch(request, None, None)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 403)

    @patch('lti_provider.views.render_courseware')
    def test_lti_consumer_record_supplemented_with_guid(self, _render):
        self.mock_verify.return_value = False

        request = build_launch_request(LTI_OPTIONAL_PARAMS)
        with self.assertNumQueries(3):
            views.lti_launch(request, None, None)
        consumer = models.LtiConsumer.objects.get(
            consumer_key=LTI_DEFAULT_PARAMS['oauth_consumer_key']
        )
        self.assertEqual(consumer.instance_guid, u'consumer instance guid')


class LtiLaunchTestRender(LtiTestMixin, RenderXBlockTestMixin, ModuleStoreTestCase):
    """
    Tests for the rendering returned by lti_launch view.
    This class overrides the get_response method, which is used by
    the tests defined in RenderXBlockTestMixin.
    """
    SUCCESS_ENROLLED_STAFF_MONGO_COUNT = 9
    shard = 3

    def get_response(self, usage_key, url_encoded_params=None):
        """
        Overridable method to get the response from the endpoint that is being tested.
        """
        lti_launch_url = reverse(
            'lti_provider_launch',
            kwargs={
                'course_id': unicode(self.course.id),
                'usage_id': unicode(usage_key)
            }
        )
        if url_encoded_params:
            lti_launch_url += '?' + url_encoded_params

        return self.client.post(lti_launch_url, data=LTI_DEFAULT_PARAMS)

    # The following test methods override the base tests for verifying access
    # by unenrolled and unauthenticated students, since there is a discrepancy
    # of access rules between the 2 endpoints (LTI and xBlock_render).
    # TODO fix this access discrepancy to the same underlying data.

    def test_unenrolled_student(self):
        """
        Override since LTI allows access to unenrolled students.
        """
        self.setup_course()
        self.setup_user(admin=False, enroll=False, login=True)
        self.verify_response()

    def test_unauthenticated(self):
        """
        Override since LTI allows access to unauthenticated users.
        """
        self.setup_course()
        self.setup_user(admin=False, enroll=True, login=False)
        self.verify_response()

    def get_success_enrolled_staff_mongo_count(self):
        """
        Override because mongo queries are higher for this
        particular test. This has not been investigated exhaustively
        as mongo is no longer used much, and removing user_partitions
        from inheritance fixes the problem.

        # The 9 mongoDB calls include calls for
        # Old Mongo:
        #   (1) fill_in_run
        #   (2) get_course in get_course_with_access
        #   (3) get_item for HTML block in get_module_by_usage_id
        #   (4) get_parent when loading HTML block
        #   (5)-(8) calls related to the inherited user_partitions field.
        #   (9) edx_notes descriptor call to get_course
        """
        return 9
