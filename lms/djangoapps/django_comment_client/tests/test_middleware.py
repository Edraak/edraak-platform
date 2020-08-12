import json

import django.http
from django.test import TestCase
from six import text_type

import django_comment_client.middleware as middleware
import lms.lib.comment_client


class AjaxExceptionTestCase(TestCase):
    shard = 1

    def setUp(self):
        super(AjaxExceptionTestCase, self).setUp()
        self.a = middleware.AjaxExceptionMiddleware()
        self.request1 = django.http.HttpRequest()
        self.request0 = django.http.HttpRequest()
        self.exception1 = lms.lib.comment_client.CommentClientRequestError('{}', 401)
        self.exception2 = lms.lib.comment_client.CommentClientRequestError('Foo!', 404)
        self.exception0 = lms.lib.comment_client.CommentClient500Error("Holy crap the server broke!")
        self.request1.META['HTTP_X_REQUESTED_WITH'] = "XMLHttpRequest"
        self.request0.META['HTTP_X_REQUESTED_WITH'] = "SHADOWFAX"

    def test_process_exception(self):
        response1 = self.a.process_exception(self.request1, self.exception1)
        self.assertIsInstance(response1, middleware.JsonError)
        self.assertEqual(self.exception1.status_code, response1.status_code)
        self.assertEqual(
            {"errors": json.loads(text_type(self.exception1))},
            json.loads(response1.content)
        )

        response2 = self.a.process_exception(self.request1, self.exception2)
        self.assertIsInstance(response2, middleware.JsonError)
        self.assertEqual(self.exception2.status_code, response2.status_code)
        self.assertEqual(
            {"errors": [text_type(self.exception2)]},
            json.loads(response2.content)
        )

        self.assertIsNone(self.a.process_exception(self.request1, self.exception0))
        self.assertIsNone(self.a.process_exception(self.request0, self.exception1))
        self.assertIsNone(self.a.process_exception(self.request0, self.exception0))
