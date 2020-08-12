"""
Acceptance test tasks
"""
from __future__ import print_function
from optparse import make_option

from paver.easy import cmdopts, needs

from pavelib.utils.passthrough_opts import PassthroughTask
from pavelib.utils.test.suites import AcceptanceTestSuite
from pavelib.utils.timer import timed

try:
    from pygments.console import colorize
except ImportError:
    colorize = lambda color, text: text

__test__ = False  # do not collect


@needs(
    'pavelib.prereqs.install_prereqs',
    'pavelib.utils.test.utils.clean_reports_dir',
)
@cmdopts([
    ("system=", "s", "System to act on"),
    ("default-store=", "m", "Default modulestore to use for course creation"),
    ("fasttest", "a", "Run without collectstatic"),
    make_option("--verbose", action="store_const", const=2, dest="verbosity"),
    make_option("-q", "--quiet", action="store_const", const=0, dest="verbosity"),
    make_option("-v", "--verbosity", action="count", dest="verbosity"),
    ("default_store=", None, "deprecated in favor of default-store"),
    ('extra_args=', 'e', 'deprecated, pass extra options directly in the paver commandline'),
])
@PassthroughTask
@timed
def test_acceptance(options, passthrough_options):
    """
    Run the acceptance tests for either lms or cms
    """
    opts = {
        'fasttest': getattr(options, 'fasttest', False),
        'system': getattr(options, 'system', None),
        'default_store': getattr(options, 'default_store', None),
        'verbosity': getattr(options, 'verbosity', 3),
        'extra_args': getattr(options, 'extra_args', ''),
        'pdb': getattr(options, 'pdb', False),
        'passthrough_options': passthrough_options,
    }

    if opts['system'] not in ['cms', 'lms']:
        msg = colorize(
            'red',
            'No system specified, running tests for both cms and lms.'
        )
        print(msg)
    if opts['default_store'] not in ['draft', 'split']:
        msg = colorize(
            'red',
            'No modulestore specified, running tests for both draft and split.'
        )
        print(msg)

    suite = AcceptanceTestSuite('{} acceptance'.format(opts['system']), **opts)
    suite.run()
