"""
Helper functions for test tasks
"""
from __future__ import print_function
import os
import re
import subprocess

from paver.easy import cmdopts, sh, task

from pavelib.utils.envs import Env
from pavelib.utils.timer import timed

try:
    from bok_choy.browser import browser
except ImportError:
    browser = None

MONGO_PORT_NUM = int(os.environ.get('EDXAPP_TEST_MONGO_PORT', '27017'))
MINIMUM_FIREFOX_VERSION = 28.0

__test__ = False  # do not collect


@task
@timed
def clean_test_files():
    """
    Clean fixture files used by tests and .pyc files
    """
    sh("git clean -fqdx test_root/logs test_root/data test_root/staticfiles test_root/uploads")
    # This find command removes all the *.pyc files that aren't in the .git
    # directory.  See this blog post for more details:
    # http://nedbatchelder.com/blog/201505/be_careful_deleting_files_around_git.html
    sh(r"find . -name '.git' -prune -o -name '*.pyc' -exec rm {} \;")
    sh("rm -rf test_root/log/auto_screenshots/*")
    sh("rm -rf /tmp/mako_[cl]ms")


@task
@timed
def ensure_clean_package_lock():
    """
    Ensure no untracked changes have been made in the current git context.
    """
    sh("""
      git diff --name-only --exit-code package-lock.json ||
      (echo \"Dirty package-lock.json, run 'npm install' and commit the generated changes\" && exit 1)
    """)


def clean_dir(directory):
    """
    Delete all the files from the specified directory.
    """
    # We delete the files but preserve the directory structure
    # so that coverage.py has a place to put the reports.
    sh('find {dir} -type f -delete'.format(dir=directory))


@task
@cmdopts([
    ('skip-clean', 'C', 'skip cleaning repository before running tests'),
    ('skip_clean', None, 'deprecated in favor of skip-clean'),
])
@timed
def clean_reports_dir(options):
    """
    Clean coverage files, to ensure that we don't use stale data to generate reports.
    """
    if getattr(options, 'skip_clean', False):
        print('--skip-clean is set, skipping...')
        return

    # We delete the files but preserve the directory structure
    # so that coverage.py has a place to put the reports.
    reports_dir = Env.REPORT_DIR.makedirs_p()
    clean_dir(reports_dir)


@task
@timed
def clean_mongo():
    """
    Clean mongo test databases
    """
    sh("mongo {host}:{port} {repo_root}/scripts/delete-mongo-test-dbs.js".format(
        host=Env.MONGO_HOST,
        port=MONGO_PORT_NUM,
        repo_root=Env.REPO_ROOT,
    ))


def check_firefox_version():
    """
    Check that firefox is the correct version.
    """
    if 'BOK_CHOY_HOSTNAME' in os.environ:
        # Firefox is running in a separate Docker container; get its version via Selenium
        driver = browser()
        capabilities = driver.capabilities
        if capabilities['browserName'].lower() == 'firefox':
            firefox_version_regex = re.compile(r'^\d+\.\d+')
            version_key = 'browserVersion' if 'browserVersion' in capabilities else 'version'
            try:
                firefox_ver = float(firefox_version_regex.search(capabilities[version_key]).group(0))
            except AttributeError:
                firefox_ver = 0.0
        else:
            firefox_ver = 0.0
        driver.close()
        if firefox_ver < MINIMUM_FIREFOX_VERSION:
            raise Exception(
                'Required firefox version not found.\n'
                'Expected: {expected_version}; Actual: {actual_version}.\n\n'
                'Make sure that the edx.devstack.firefox container is up-to-date and running\n'
                '\t{expected_version}'.format(
                    actual_version=firefox_ver,
                    expected_version=MINIMUM_FIREFOX_VERSION
                )
            )
        return

    # Firefox will be run as a local process
    expected_firefox_ver = "Mozilla Firefox " + str(MINIMUM_FIREFOX_VERSION)
    firefox_ver_string = subprocess.check_output("firefox --version", shell=True).strip()
    firefox_version_regex = re.compile(r"Mozilla Firefox (\d+.\d+)")
    try:
        firefox_ver = float(firefox_version_regex.search(firefox_ver_string).group(1))
    except AttributeError:
        firefox_ver = 0.0
    debian_location = 'https://s3.amazonaws.com/vagrant.testeng.edx.org/'
    debian_package = 'firefox-mozilla-build_42.0-0ubuntu1_amd64.deb'
    debian_path = '{location}{package}'.format(location=debian_location, package=debian_package)

    if firefox_ver < MINIMUM_FIREFOX_VERSION:
        raise Exception(
            'Required firefox version not found.\n'
            'Expected: {expected_version}; Actual: {actual_version}.\n\n'
            'As the vagrant user in devstack, run the following:\n\n'
            '\t$ sudo wget -O /tmp/firefox_42.deb {debian_path}\n'
            '\t$ sudo apt-get remove firefox\n\n'
            '\t$ sudo gdebi -nq /tmp/firefox_42.deb\n\n'
            'Confirm the new version:\n'
            '\t$ firefox --version\n'
            '\t{expected_version}'.format(
                actual_version=firefox_ver,
                expected_version=expected_firefox_ver,
                debian_path=debian_path
            )
        )
