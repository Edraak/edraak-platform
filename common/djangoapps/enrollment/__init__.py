"""
Enrollment API helpers and settings
"""


class Timer(object):
    last_time = None
    last_time_name = None

    @classmethod
    def log_time(cls, name, level):
        import timeit
        time = timeit.default_timer()
        execution_time = stop - start

        if cls.last_time and cls.last_time_name:
            extra = '{time_diff} since {name}'.format(
                time_diff=time - cls.last_time,
                name=cls.last_time_name,
            )
        else:
            extra = 'no last time'

        cls.last_time = time
        cls.last_time_name = name
        log.info('%s edraak_timer: %s [%s]', level * ' >', name, extra)
