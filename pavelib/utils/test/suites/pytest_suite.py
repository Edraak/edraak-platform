"""
Classes used for defining and running pytest test suites
"""
import os
from glob import glob
from pavelib.utils.test import utils as test_utils
from pavelib.utils.test.suites.suite import TestSuite
from pavelib.utils.envs import Env

__test__ = False  # do not collect


class PytestSuite(TestSuite):
    """
    A subclass of TestSuite with extra methods that are specific
    to pytest tests
    """
    def __init__(self, *args, **kwargs):
        super(PytestSuite, self).__init__(*args, **kwargs)
        self.failed_only = kwargs.get('failed_only', False)
        self.fail_fast = kwargs.get('fail_fast', False)
        self.run_under_coverage = kwargs.get('with_coverage', True)
        django_version = kwargs.get('django_version', None)
        if django_version is None:
            self.django_toxenv = None
        else:
            self.django_toxenv = 'py27-django{}'.format(django_version.replace('.', ''))
        self.disable_capture = kwargs.get('disable_capture', None)
        self.report_dir = Env.REPORT_DIR / self.root

        # If set, put reports for run in "unique" directories.
        # The main purpose of this is to ensure that the reports can be 'slurped'
        # in the main jenkins flow job without overwriting the reports from other
        # build steps. For local development/testing, this shouldn't be needed.
        if os.environ.get("SHARD", None):
            shard_str = "shard_{}".format(os.environ.get("SHARD"))
            self.report_dir = self.report_dir / shard_str
        self.xunit_report = self.report_dir / "nosetests.xml"

        self.cov_args = kwargs.get('cov_args', '')

    def __enter__(self):
        super(PytestSuite, self).__enter__()
        self.report_dir.makedirs_p()

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Cleans mongo afer the tests run.
        """
        super(PytestSuite, self).__exit__(exc_type, exc_value, traceback)
        test_utils.clean_mongo()

    def _under_coverage_cmd(self, cmd):
        """
        If self.run_under_coverage is True, it returns the arg 'cmd'
        altered to be run under coverage. It returns the command
        unaltered otherwise.
        """
        if self.run_under_coverage:
            cmd.append('--cov')
            cmd.append('--cov-report=')

        return cmd

    @staticmethod
    def is_success(exit_code):
        """
        An exit code of zero means all tests passed, 5 means no tests were
        found.
        """
        return exit_code in [0, 5]

    @property
    def test_options_flags(self):
        """
        Takes the test options and returns the appropriate flags
        for the command.
        """
        opts = []

        # Handle "--failed" as a special case: we want to re-run only
        # the tests that failed within our Django apps
        # This sets the --last-failed flag for the pytest command, so this
        # functionality is the same as described in the pytest documentation
        if self.failed_only:
            opts.append("--last-failed")

        # This makes it so we use pytest's fail-fast feature in two cases.
        # Case 1: --fail-fast is passed as an arg in the paver command
        # Case 2: The environment variable TESTS_FAIL_FAST is set as True
        env_fail_fast_set = (
            'TESTS_FAIL_FAST' in os.environ and os.environ['TEST_FAIL_FAST']
        )

        if self.fail_fast or env_fail_fast_set:
            opts.append("--exitfirst")

        return opts


class SystemTestSuite(PytestSuite):
    """
    TestSuite for lms and cms python unit tests
    """
    def __init__(self, *args, **kwargs):
        super(SystemTestSuite, self).__init__(*args, **kwargs)
        self.eval_attr = kwargs.get('eval_attr', None)
        self.test_id = kwargs.get('test_id', self._default_test_id)
        self.fasttest = kwargs.get('fasttest', False)

        self.processes = kwargs.get('processes', None)
        self.randomize = kwargs.get('randomize', None)
        self.settings = kwargs.get('settings', Env.TEST_SETTINGS)
        self.xdist_ip_addresses = kwargs.get('xdist_ip_addresses', None)

        if self.processes is None:
            # Don't use multiprocessing by default
            self.processes = 0

        self.processes = int(self.processes)

    def _under_coverage_cmd(self, cmd):
        """
        If self.run_under_coverage is True, it returns the arg 'cmd'
        altered to be run under coverage. It returns the command
        unaltered otherwise.
        """
        if self.run_under_coverage:
            cmd.append('--cov')
            cmd.append('--cov-report=')

        return cmd

    @property
    def cmd(self):
        if self.django_toxenv:
            cmd = ['tox', '-e', self.django_toxenv, '--']
        else:
            cmd = []
        cmd.extend([
            'python',
            '-Wd',
            '-m',
            'pytest',
            '--ds={}'.format('{}.envs.{}'.format(self.root, self.settings)),
            "--junitxml={}".format(self.xunit_report),
        ])
        cmd.extend(self.test_options_flags)
        if self.verbosity < 1:
            cmd.append("--quiet")
        elif self.verbosity > 1:
            cmd.append("--verbose")

        if self.disable_capture:
            cmd.append("-s")
        if self.xdist_ip_addresses:
            cmd.append('--dist=loadscope')
            if self.processes <= 0:
                xdist_remote_processes = 1
            else:
                xdist_remote_processes = self.processes
            for ip in self.xdist_ip_addresses.split(','):
                # The django settings runtime command does not propagate to xdist remote workers
                django_env_var_cmd = 'export DJANGO_SETTINGS_MODULE={}' \
                                     .format('{}.envs.{}'.format(self.root, self.settings))
                xdist_string = '--tx {}*ssh="ubuntu@{} -o StrictHostKeyChecking=no"' \
                               '//python="source /edx/app/edxapp/edxapp_env; {}; python"' \
                               '//chdir="/edx/app/edxapp/edx-platform"' \
                               .format(xdist_remote_processes, ip, django_env_var_cmd)
                cmd.append(xdist_string)
            for rsync_dir in Env.rsync_dirs():
                cmd.append('--rsyncdir {}'.format(rsync_dir))
        else:
            if self.processes == -1:
                cmd.append('-n auto')
                cmd.append('--dist=loadscope')
            elif self.processes != 0:
                cmd.append('-n {}'.format(self.processes))
                cmd.append('--dist=loadscope')

        if not self.randomize:
            cmd.append('-p no:randomly')
        if self.eval_attr:
            cmd.append("-a '{}'".format(self.eval_attr))

        cmd.extend(self.passthrough_options)
        cmd.append(self.test_id)

        return self._under_coverage_cmd(cmd)

    @property
    def _default_test_id(self):
        """
        If no test id is provided, we need to limit the test runner
        to the Djangoapps we want to test.  Otherwise, it will
        run tests on all installed packages. We do this by
        using a default test id.
        """
        # We need to use $DIR/*, rather than just $DIR so that
        # pytest will import them early in the test process,
        # thereby making sure that we load any django models that are
        # only defined in test files.
        default_test_globs = [
            "{system}/djangoapps/*".format(system=self.root),
            "common/djangoapps/*",
            "openedx/core/djangoapps/*",
            "openedx/tests/*",
            "openedx/core/lib/*",
        ]
        if self.root in ('lms', 'cms'):
            default_test_globs.append("{system}/lib/*".format(system=self.root))

        if self.root == 'lms':
            default_test_globs.append("{system}/tests.py".format(system=self.root))
            default_test_globs.append("openedx/core/djangolib/*")
            default_test_globs.append("openedx/features")

        def included(path):
            """
            Should this path be included in the pytest arguments?
            """
            if path.endswith(Env.IGNORED_TEST_DIRS):
                return False
            return path.endswith('.py') or os.path.isdir(path)

        default_test_paths = []
        for path_glob in default_test_globs:
            if '*' in path_glob:
                default_test_paths += [path for path in glob(path_glob) if included(path)]
            else:
                default_test_paths += [path_glob]
        return ' '.join(default_test_paths)


class LibTestSuite(PytestSuite):
    """
    TestSuite for edx-platform/common/lib python unit tests
    """
    def __init__(self, *args, **kwargs):
        super(LibTestSuite, self).__init__(*args, **kwargs)
        self.append_coverage = kwargs.get('append_coverage', False)
        self.test_id = kwargs.get('test_id', self.root)
        self.eval_attr = kwargs.get('eval_attr', None)
        self.xdist_ip_addresses = kwargs.get('xdist_ip_addresses', None)
        self.randomize = kwargs.get('randomize', None)
        self.processes = kwargs.get('processes', None)

        if self.processes is None:
            # Don't use multiprocessing by default
            self.processes = 0

        self.processes = int(self.processes)

    @property
    def cmd(self):
        if self.django_toxenv:
            cmd = ['tox', '-e', self.django_toxenv, '--']
        else:
            cmd = []
        cmd.extend([
            'python',
            '-Wd',
            '-m',
            'pytest',
            '--junitxml={}'.format(self.xunit_report),
        ])
        cmd.extend(self.passthrough_options + self.test_options_flags)
        if self.verbosity < 1:
            cmd.append("--quiet")
        elif self.verbosity > 1:
            cmd.append("--verbose")
        if self.disable_capture:
            cmd.append("-s")

        if self.xdist_ip_addresses:
            cmd.append('--dist=loadscope')
            if self.processes <= 0:
                xdist_remote_processes = 1
            else:
                xdist_remote_processes = self.processes
            for ip in self.xdist_ip_addresses.split(','):
                # The django settings runtime command does not propagate to xdist remote workers
                if 'pavelib/paver_tests' in self.test_id:
                    django_env_var_cmd = "export DJANGO_SETTINGS_MODULE='lms.envs.test'"
                else:
                    django_env_var_cmd = "export DJANGO_SETTINGS_MODULE='openedx.tests.settings'"
                xdist_string = '--tx {}*ssh="ubuntu@{} -o StrictHostKeyChecking=no"' \
                               '//python="source /edx/app/edxapp/edxapp_env; {}; python"' \
                               '//chdir="/edx/app/edxapp/edx-platform"' \
                               .format(xdist_remote_processes, ip, django_env_var_cmd)
                cmd.append(xdist_string)
            for rsync_dir in Env.rsync_dirs():
                cmd.append('--rsyncdir {}'.format(rsync_dir))
        else:
            if self.processes == -1:
                cmd.append('-n auto')
                cmd.append('--dist=loadscope')
            elif self.processes != 0:
                cmd.append('-n {}'.format(self.processes))
                cmd.append('--dist=loadscope')

        if not self.randomize:
            cmd.append("-p no:randomly")
        if self.eval_attr:
            cmd.append("-a '{}'".format(self.eval_attr))

        cmd.append(self.test_id)

        return self._under_coverage_cmd(cmd)

    def _under_coverage_cmd(self, cmd):
        """
        If self.run_under_coverage is True, it returns the arg 'cmd'
        altered to be run under coverage. It returns the command
        unaltered otherwise.
        """
        if self.run_under_coverage:
            cmd.append('--cov')
            if self.append_coverage:
                cmd.append('--cov-append')
            cmd.append('--cov-report=')

        return cmd
