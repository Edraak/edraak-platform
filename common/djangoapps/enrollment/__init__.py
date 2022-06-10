"""
Enrollment API helpers and settings
"""
import timeit
import logging
from contextlib import contextmanager

log = logging.getLogger(__name__)


@contextmanager
def time_block(name, level):
    start_time = timeit.default_timer()
    log.info('%s edraak_time_block: %s [start]', level * ' >>', name)
    try:
        yield
    finally:
        diff = timeit.default_timer() - start_time
        log.info('%s edraak_time_block: %s [end: %s ms]', level * ' >>', name, diff * 1000)
