"""
Helper functions for bok_choy test tasks
"""
from __future__ import print_function
import httplib
import os
import subprocess
import sys
import time

from paver import tasks
from paver.easy import cmdopts, needs, sh, task

from pavelib.utils.envs import Env
from pavelib.utils.process import run_background_process
from pavelib.utils.test.bokchoy_options import BOKCHOY_COVERAGERC, BOKCHOY_DEFAULT_STORE, BOKCHOY_DEFAULT_STORE_DEPR
from pavelib.utils.timer import timed

try:
    from pygments.console import colorize
except ImportError:
    colorize = lambda color, text: text

__test__ = False  # do not collect


@task
@cmdopts([BOKCHOY_COVERAGERC, BOKCHOY_DEFAULT_STORE, BOKCHOY_DEFAULT_STORE_DEPR])
@timed
def start_servers(options):
    """
    Start the servers we will run tests on, returns PIDs for servers.
    """
    coveragerc = options.get('coveragerc', None)

    def start_server(cmd, logfile, cwd=None):
        """
        Starts a single server.
        """
        print(cmd, logfile)
        run_background_process(cmd, out_log=logfile, err_log=logfile, cwd=cwd)

    for service, info in Env.BOK_CHOY_SERVERS.iteritems():
        address = "0.0.0.0:{}".format(info['port'])
        cmd = ("DEFAULT_STORE={default_store} ").format(default_store=options.default_store)
        if coveragerc:
            cmd += ("coverage run --rcfile={coveragerc} -m ").format(coveragerc=coveragerc)
        else:
            cmd += "python -m "
        cmd += (
            "manage {service} --settings {settings} runserver "
            "{address} --traceback --noreload".format(
                service=service,
                settings=Env.SETTINGS,
                address=address,
            )
        )
        start_server(cmd, info['log'])

    for service, info in Env.BOK_CHOY_STUBS.iteritems():
        cmd = (
            "python -m stubs.start {service} {port} "
            "{config}".format(
                service=service,
                port=info['port'],
                config=info.get('config', ''),
            )
        )
        start_server(cmd, info['log'], cwd=Env.BOK_CHOY_STUB_DIR)


def wait_for_server(server, port):
    """
    Wait for a server to respond with status 200
    """
    print(
        "Checking server {server} on port {port}".format(
            server=server,
            port=port,
        )
    )

    if tasks.environment.dry_run:
        return True

    attempts = 0
    server_ok = False

    while attempts < 120:
        try:
            connection = httplib.HTTPConnection(server, port, timeout=10)
            connection.request('GET', '/')
            response = connection.getresponse()

            if int(response.status) == 200:
                server_ok = True
                break
        except:  # pylint: disable=bare-except
            pass

        attempts += 1
        time.sleep(1)

    return server_ok


def wait_for_test_servers():
    """
    Wait until we get a successful response from the servers or time out
    """

    for service, info in Env.BOK_CHOY_SERVERS.iteritems():
        ready = wait_for_server(info['host'], info['port'])
        if not ready:
            msg = colorize(
                "red",
                "Could not contact {} test server".format(service)
            )
            print(msg)
            sys.exit(1)


def is_mongo_running():
    """
    Returns True if mongo is running, False otherwise.
    """
    # The mongo command will connect to the service,
    # failing with a non-zero exit code if it cannot connect.
    output = os.popen('mongo --host {} --eval "print(\'running\')"'.format(Env.MONGO_HOST)).read()
    return output and "running" in output


def is_memcache_running():
    """
    Returns True if memcache is running, False otherwise.
    """
    # Attempt to set a key in memcache. If we cannot do so because the
    # service is not available, then this will return False.
    return Env.BOK_CHOY_CACHE.set('test', 'test')


def is_mysql_running():
    """
    Returns True if mysql is running, False otherwise.
    """
    # We need to check whether or not mysql is running as a process
    # even if it is not daemonized.
    with open(os.devnull, 'w') as os_devnull:
        #pgrep returns the PID, which we send to /dev/null
        returncode = subprocess.call("pgrep mysqld", stdout=os_devnull, shell=True)
    return returncode == 0


@task
@timed
def clear_mongo():
    """
    Clears mongo database.
    """
    sh(
        "mongo --host {} {} --eval 'db.dropDatabase()' > /dev/null".format(
            Env.MONGO_HOST,
            Env.BOK_CHOY_MONGO_DATABASE,
        )
    )


@task
@timed
def check_mongo():
    """
    Check that mongo is running
    """
    if not is_mongo_running():
        msg = colorize('red', "Mongo is not running locally.")
        print(msg)
        sys.exit(1)


@task
@timed
def check_memcache():
    """
    Check that memcache is running
    """
    if not is_memcache_running():
        msg = colorize('red', "Memcache is not running locally.")
        print(msg)
        sys.exit(1)


@task
@timed
def check_mysql():
    """
    Check that mysql is running
    """
    if 'BOK_CHOY_HOSTNAME' in os.environ:
        # mysql should be running in a separate Docker container
        return
    if not is_mysql_running():
        msg = colorize('red', "MySQL is not running locally.")
        print(msg)
        sys.exit(1)


@task
@needs('check_mongo', 'check_memcache', 'check_mysql')
@timed
def check_services():
    """
    Check that all required services are running
    """
    pass
