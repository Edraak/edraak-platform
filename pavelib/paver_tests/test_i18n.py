"""
Tests for pavelib/i18n.py.
"""

import os
import textwrap
import unittest

from mock import mock_open, patch
from paver.easy import call_task, task

import pavelib.i18n
from pavelib.paver_tests.utils import PaverTestCase
from pavelib.utils.envs import Env


TX_CONFIG_SIMPLE = """\
[main]
host = https://www.transifex.com

[edx-platform.django-partial]
file_filter = conf/locale/<lang>/LC_MESSAGES/django-partial.po
source_file = conf/locale/en/LC_MESSAGES/django-partial.po
source_lang = en
type = PO

[edx-platform.django-studio]
file_filter = conf/locale/<lang>/LC_MESSAGES/django-studio.po
source_file = conf/locale/en/LC_MESSAGES/django-studio.po
source_lang = en
type = PO

"""

TX_CONFIG_RELEASE = TX_CONFIG_SIMPLE + """\
[edx-platform.release-zebrawood]
file_filter = conf/locale/<lang>/LC_MESSAGES/django.po
source_file = conf/locale/en/LC_MESSAGES/django.po
source_lang = en
type = PO

[edx-platform.release-zebrawood-js]
file_filter = conf/locale/<lang>/LC_MESSAGES/djangojs.po
source_file = conf/locale/en/LC_MESSAGES/djangojs.po
source_lang = en
type = PO
"""


def mocked_i18n_open(*content):
    """
    Helper decorator to mock open() in pavelib.i18n.

    Arguments:
        content (str): any number of strings, which are dedented, then
            concatenated, and then returned as f.read() when pavelib.i18n opens
            a file.

    """
    read_data = "".join(textwrap.dedent(c) for c in content)
    return patch.object(pavelib.i18n, 'open', create=True, new=mock_open(read_data=read_data))


@task
def do_nothing():
    """
    Don't do anything, for replacing prerequisite tasks we want to skip.
    """
    pass


class FindReleaseResourcesTest(unittest.TestCase):
    """
    Tests of pavelib/i18n.py:find_release_resources.
    """
    @mocked_i18n_open(TX_CONFIG_SIMPLE)
    def test_no_resources(self):
        errmsg = r"You need two release-\* resources defined to use this command."
        with self.assertRaisesRegexp(ValueError, errmsg):
            pavelib.i18n.find_release_resources()

    @mocked_i18n_open(TX_CONFIG_SIMPLE, """\
        [edx-platform.release-zebrawood]
        file_filter = conf/locale/<lang>/LC_MESSAGES/django.po
        source_file = conf/locale/en/LC_MESSAGES/django.po
        source_lang = en
        type = PO
        """)
    def test_one_resource(self):
        errmsg = r"Strange Transifex config! Found these release-\* resources:\nedx-platform.release-zebrawood"
        with self.assertRaisesRegexp(ValueError, errmsg):
            pavelib.i18n.find_release_resources()

    @mocked_i18n_open(TX_CONFIG_RELEASE)
    def test_good_resources(self):
        self.assertEqual(
            pavelib.i18n.find_release_resources(),
            ['edx-platform.release-zebrawood', 'edx-platform.release-zebrawood-js'],
        )


class ReleasePushPullTest(PaverTestCase):
    """
    Tests of i18n_release_push and i18n_release_pull.
    """
    @mocked_i18n_open(TX_CONFIG_SIMPLE)
    @patch.object(pavelib.i18n, 'i18n_generate', new=do_nothing)
    def test_cant_push_nothing(self):
        with self.assertRaises(SystemExit) as sysex:
            pavelib.i18n.i18n_release_push()
        # Check that we exited with a failure status code.
        self.assertEqual(sysex.exception.args, (1,))

    @mocked_i18n_open(TX_CONFIG_SIMPLE)
    def test_cant_pull_nothing(self):
        with self.assertRaises(SystemExit) as sysex:
            pavelib.i18n.i18n_release_pull()
        # Check that we exited with a failure status code.
        self.assertEqual(sysex.exception.args, (1,))

    @mocked_i18n_open(TX_CONFIG_RELEASE)
    @patch.object(pavelib.i18n, 'i18n_generate', new=do_nothing)
    @patch.object(pavelib.i18n, 'sh')
    def test_can_push_release(self, mock_sh):
        pavelib.i18n.i18n_release_push()
        mock_sh.assert_called_once_with(
            'i18n_tool transifex push edx-platform.release-zebrawood edx-platform.release-zebrawood-js'
        )

    @mocked_i18n_open(TX_CONFIG_RELEASE)
    @patch.object(pavelib.i18n, 'sh')
    def test_can_pull_release(self, mock_sh):
        pavelib.i18n.i18n_release_pull()
        mock_sh.assert_called_once_with(
            'i18n_tool transifex pull edx-platform.release-zebrawood edx-platform.release-zebrawood-js'
        )


class TestI18nDummy(PaverTestCase):
    """
    Test the Paver i18n_dummy task.
    """
    def setUp(self):
        super(TestI18nDummy, self).setUp()

        # Mock the paver @needs decorator for i18n_extract
        self._mock_paver_needs = patch.object(pavelib.i18n.i18n_extract, 'needs').start()
        self._mock_paver_needs.return_value = 0

        # Cleanup mocks
        self.addCleanup(self._mock_paver_needs.stop)

    def test_i18n_dummy(self):
        """
        Test the "i18n_dummy" task.
        """
        self.reset_task_messages()
        os.environ['NO_PREREQ_INSTALL'] = "true"
        call_task('pavelib.i18n.i18n_dummy', options={"settings": Env.TEST_SETTINGS})
        self.assertEquals(
            self.task_messages,
            [
                u'i18n_tool extract',
                u'i18n_tool dummy',
                u'i18n_tool generate -v',
                u'python manage.py lms --settings={} compilejsi18n'.format(Env.TEST_SETTINGS),
                u'python manage.py cms --settings={} compilejsi18n'.format(Env.TEST_SETTINGS),
            ]
        )
