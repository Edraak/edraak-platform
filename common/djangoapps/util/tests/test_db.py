"""Tests for util.db module."""

import threading
import time
import unittest

import ddt
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.db.transaction import TransactionManagementError, atomic
from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.utils.six import StringIO

from util.db import commit_on_success, enable_named_outer_atomic, generate_int_id, outer_atomic


def do_nothing():
    """Just return."""
    return


@ddt.ddt
class TransactionManagersTestCase(TransactionTestCase):
    """
    Tests commit_on_success and outer_atomic.

    Note: This TestCase only works with MySQL.

    To test do: "./manage.py lms --settings=test_with_mysql test util.tests.test_db"
    """
    DECORATORS = {
        'outer_atomic': outer_atomic(),
        'outer_atomic_read_committed': outer_atomic(read_committed=True),
        'commit_on_success': commit_on_success(),
        'commit_on_success_read_committed': commit_on_success(read_committed=True),
    }

    @ddt.data(
        ('outer_atomic', IntegrityError, None, True),
        ('outer_atomic_read_committed', type(None), False, True),
        ('commit_on_success', IntegrityError, None, True),
        ('commit_on_success_read_committed', type(None), False, True),
    )
    @ddt.unpack
    def test_concurrent_requests(self, transaction_decorator_name, exception_class, created_in_1, created_in_2):
        """
        Test that when isolation level is set to READ COMMITTED get_or_create()
        for the same row in concurrent requests does not raise an IntegrityError.
        """
        transaction_decorator = self.DECORATORS[transaction_decorator_name]
        if connection.vendor != 'mysql':
            raise unittest.SkipTest('Only works on MySQL.')

        class RequestThread(threading.Thread):
            """ A thread which runs a dummy view."""
            def __init__(self, delay, **kwargs):
                super(RequestThread, self).__init__(**kwargs)
                self.delay = delay
                self.status = {}

            @transaction_decorator
            def run(self):
                """A dummy view."""
                try:
                    try:
                        User.objects.get(username='student', email='student@edx.org')
                    except User.DoesNotExist:
                        pass
                    else:
                        raise AssertionError('Did not raise User.DoesNotExist.')

                    if self.delay > 0:
                        time.sleep(self.delay)

                    __, created = User.objects.get_or_create(username='student', email='student@edx.org')
                except Exception as exception:  # pylint: disable=broad-except
                    self.status['exception'] = exception
                else:
                    self.status['created'] = created

        thread1 = RequestThread(delay=1)
        thread2 = RequestThread(delay=0)

        thread1.start()
        thread2.start()
        thread2.join()
        thread1.join()

        self.assertIsInstance(thread1.status.get('exception'), exception_class)
        self.assertEqual(thread1.status.get('created'), created_in_1)

        self.assertIsNone(thread2.status.get('exception'))
        self.assertEqual(thread2.status.get('created'), created_in_2)

    def test_outer_atomic_nesting(self):
        """
        Test that outer_atomic raises an error if it is nested inside
        another atomic.
        """
        if connection.vendor != 'mysql':
            raise unittest.SkipTest('Only works on MySQL.')

        outer_atomic()(do_nothing)()

        with atomic():
            atomic()(do_nothing)()

        with outer_atomic():
            atomic()(do_nothing)()

        with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
            with atomic():
                outer_atomic()(do_nothing)()

        with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
            with outer_atomic():
                outer_atomic()(do_nothing)()

    def test_commit_on_success_nesting(self):
        """
        Test that commit_on_success raises an error if it is nested inside
        atomic or if the isolation level is changed when it is nested
        inside another commit_on_success.
        """
        # pylint: disable=not-callable

        if connection.vendor != 'mysql':
            raise unittest.SkipTest('Only works on MySQL.')

        commit_on_success(read_committed=True)(do_nothing)()

        with self.assertRaisesRegexp(TransactionManagementError, 'Cannot change isolation level when nested.'):
            with commit_on_success():
                commit_on_success(read_committed=True)(do_nothing)()

        with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
            with atomic():
                commit_on_success(read_committed=True)(do_nothing)()

    def test_named_outer_atomic_nesting(self):
        """
        Test that a named outer_atomic raises an error only if nested in
        enable_named_outer_atomic and inside another atomic.
        """
        if connection.vendor != 'mysql':
            raise unittest.SkipTest('Only works on MySQL.')

        outer_atomic(name='abc')(do_nothing)()

        with atomic():
            outer_atomic(name='abc')(do_nothing)()

        with enable_named_outer_atomic('abc'):

            outer_atomic(name='abc')(do_nothing)()  # Not nested.

            with atomic():
                outer_atomic(name='pqr')(do_nothing)()  # Not enabled.

            with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
                with atomic():
                    outer_atomic(name='abc')(do_nothing)()

        with enable_named_outer_atomic('abc', 'def'):

            outer_atomic(name='def')(do_nothing)()  # Not nested.

            with atomic():
                outer_atomic(name='pqr')(do_nothing)()  # Not enabled.

            with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
                with atomic():
                    outer_atomic(name='def')(do_nothing)()

            with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
                with outer_atomic():
                    outer_atomic(name='def')(do_nothing)()

            with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
                with atomic():
                    outer_atomic(name='abc')(do_nothing)()

            with self.assertRaisesRegexp(TransactionManagementError, 'Cannot be inside an atomic block.'):
                with outer_atomic():
                    outer_atomic(name='abc')(do_nothing)()


@ddt.ddt
class GenerateIntIdTestCase(TestCase):
    """Tests for `generate_int_id`"""
    @ddt.data(10)
    def test_no_used_ids(self, times):
        """
        Verify that we get a random integer within the specified range
        when there are no used ids.
        """
        minimum = 1
        maximum = times
        for __ in range(times):
            self.assertIn(generate_int_id(minimum, maximum), range(minimum, maximum + 1))

    @ddt.data(10)
    def test_used_ids(self, times):
        """
        Verify that we get a random integer within the specified range
        but not in a list of used ids.
        """
        minimum = 1
        maximum = times
        used_ids = {2, 4, 6, 8}
        for __ in range(times):
            int_id = generate_int_id(minimum, maximum, used_ids)
            self.assertIn(int_id, list(set(range(minimum, maximum + 1)) - used_ids))


class MigrationTests(TestCase):
    """
    Tests for migrations.
    """
    @override_settings(MIGRATION_MODULES={})
    def test_migrations_are_in_sync(self):
        """
        Tests that the migration files are in sync with the models.
        If this fails, you needs to run the Django command makemigrations.

        The test is set up to override MIGRATION_MODULES to ensure migrations are
        enabled for purposes of this test regardless of the overall test settings.

        TODO: Find a general way of handling the case where if we're trying to
        make a migrationless release that'll require a separate migration
        release afterwards, this test doesn't fail.
        """
        out = StringIO()
        call_command('makemigrations', dry_run=True, verbosity=3, stdout=out)
        output = out.getvalue()
        self.assertIn('No changes detected', output)
