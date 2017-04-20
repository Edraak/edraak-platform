"""
Edraak ForUs helpers
"""
from datetime import datetime
from edraak_forus.helpers import DATE_TIME_FORMAT


def build_forus_params(**kwargs):
    """
    Returns valid ForUs params.

    Any change here, will break a lot of other tests, be warned.
    """
    values = {
        'course_id': '',
        'email': '',
        'name': 'Abdulrahman (ForUs)',
        'enrollment_action': 'enroll',
        'country': 'JO',
        'level_of_education': 'hs',
        'gender': 'm',
        'year_of_birth': '1989',
        'lang': 'en',
        'time': datetime.utcnow().strftime(DATE_TIME_FORMAT),
        'forus_hmac': 'dummy_hmac',
    }

    values.update(kwargs)

    return values
