from __future__ import print_function

import logging

from django.conf import settings
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from lms.djangoapps.edraak_sendinblue.configurations import setup_sendinblue_configuration

log = logging.getLogger(__name__)


def create_contact(email, name, blacklisted):
    configuration = setup_sendinblue_configuration()

    if configuration:
        api_instance = sib_api_v3_sdk.ContactsApi(sib_api_v3_sdk.ApiClient(configuration))
        contact = sib_api_v3_sdk.CreateContact(
            email=email,
            attributes={
                "FULL_NAME": name
            },
            email_blacklisted=blacklisted,
            list_ids=[settings.EDRAAK_SENDINBLUE_LISTID, ],
            update_enabled=True
        )

        try:
            response = api_instance.create_contact(contact)
            log.info('SendInBlue contact created with response text {text}'.format(text=response))
        except ApiException as e:
            log.exception(
                "Exception when calling SendInBlue for email ({}) ContactsApi->create_contact: {}\n".format(email, e))


def update_contact(name, email, blacklisted):
    configuration = setup_sendinblue_configuration()

    if configuration:
        api_instance = sib_api_v3_sdk.ContactsApi(sib_api_v3_sdk.ApiClient(configuration))
        updated_contact = sib_api_v3_sdk.UpdateContact(
            email=email,
            attributes={
                "FULL_NAME": name
            },
            email_blacklisted=blacklisted,
        )

        try:
            response = api_instance.update_contact(email, updated_contact)
            log.info('SendInBlue contact updated with response text {text}'.format(text=response))
        except ApiException as e:
            log.exception(
                "Exception when calling SendInBlue for email ({}) ContactsApi->update_contact: %s\n".format(email, e)
            )


def delete_contact(email):
    configuration = setup_sendinblue_configuration()

    if configuration:
        api_instance = sib_api_v3_sdk.ContactsApi(sib_api_v3_sdk.ApiClient(configuration))

        try:
            response = api_instance.delete_contact(email)
            log.info('SendInBlue contact deleted with response text {text}'.format(text=response))
        except ApiException as e:
            log.exception(
                "Exception when calling SendInBlue for email ({}) ContactsApi->delete_contact: %s\n".format(email, e)
            )
