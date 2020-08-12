"""
This module contains signals / handlers related to programs.
"""
import logging

from django.dispatch import receiver

from openedx.core.djangoapps.signals.signals import COURSE_CERT_AWARDED, COURSE_CERT_CHANGED
from openedx.core.djangoapps.site_configuration import helpers

LOGGER = logging.getLogger(__name__)


@receiver(COURSE_CERT_AWARDED)
def handle_course_cert_awarded(sender, user, course_key, mode, status, **kwargs):  # pylint: disable=unused-argument
    """
    If programs is enabled and a learner is awarded a course certificate,
    schedule a celery task to process any programs certificates for which
    the learner may now be eligible.

    Args:
        sender:
            class of the object instance that sent this signal
        user:
            django.contrib.auth.User - the user to whom a cert was awarded
        course_key:
            refers to the course run for which the cert was awarded
        mode:
            mode / certificate type, e.g. "verified"
        status:
            either "downloadable" or "generating"

    Returns:
        None

    """
    # Import here instead of top of file since this module gets imported before
    # the credentials app is loaded, resulting in a Django deprecation warning.
    from openedx.core.djangoapps.credentials.models import CredentialsApiConfig

    # Avoid scheduling new tasks if certification is disabled.
    if not CredentialsApiConfig.current().is_learner_issuance_enabled:
        return

    # schedule background task to process
    LOGGER.debug(
        'handling COURSE_CERT_AWARDED: username=%s, course_key=%s, mode=%s, status=%s',
        user,
        course_key,
        mode,
        status,
    )
    # import here, because signal is registered at startup, but items in tasks are not yet able to be loaded
    from openedx.core.djangoapps.programs.tasks.v1.tasks import award_program_certificates
    award_program_certificates.delay(user.username)


@receiver(COURSE_CERT_CHANGED)
def handle_course_cert_changed(sender, user, course_key, mode, status, **kwargs):
    """
        If a learner is awarded a course certificate,
        schedule a celery task to process that course certificate

        Args:
            sender:
                class of the object instance that sent this signal
            user:
                django.contrib.auth.User - the user to whom a cert was awarded
            course_key:
                refers to the course run for which the cert was awarded
            mode:
                mode / certificate type, e.g. "verified"
            status:
                "downloadable"

        Returns:
            None

        """
    # Import here instead of top of file since this module gets imported before
    # the credentials app is loaded, resulting in a Django deprecation warning.
    from openedx.core.djangoapps.credentials.models import CredentialsApiConfig

    verbose = kwargs.get('verbose', False)
    if verbose:
        msg = "Starting handle_course_cert_changed with params: "\
            "sender [{sender}], "\
            "user [{username}], "\
            "course_key [{course_key}], "\
            "mode [{mode}], "\
            "status [{status}], "\
            "kwargs [{kw}]"\
            .format(
                sender=sender,
                username=getattr(user, 'username', None),
                course_key=str(course_key),
                mode=mode,
                status=status,
                kw=kwargs
            )

        LOGGER.info(msg)

    # Avoid scheduling new tasks if certification is disabled.
    if not CredentialsApiConfig.current().is_learner_issuance_enabled:
        if verbose:
            LOGGER.info("Skipping send cert: is_learner_issuance_enabled False")
        return

    # Avoid scheduling new tasks if learner records are disabled for this site (right now, course certs are only
    # used for learner records -- when that changes, we can remove this bit and always send course certs).
    if not helpers.get_value_for_org(course_key.org, 'ENABLE_LEARNER_RECORDS', True):
        if verbose:
            LOGGER.info(
                "Skipping send cert: ENABLE_LEARNER_RECORDS False for org [{org}]".format(
                    org=course_key.org
                )
            )
        return

    # schedule background task to process
    LOGGER.debug(
        'handling COURSE_CERT_CHANGED: username=%s, course_key=%s, mode=%s, status=%s',
        user,
        course_key,
        mode,
        status,
    )
    # import here, because signal is registered at startup, but items in tasks are not yet able to be loaded
    from openedx.core.djangoapps.programs.tasks.v1.tasks import award_course_certificate
    award_course_certificate.delay(user.username, str(course_key))
