from __future__ import print_function

import logging

from django.conf import settings
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from lms.djangoapps.edraak_sendinblue.configurations import setup_sendinblue_configuration


log = logging.getLogger(__name__)


def create_contact(username, email, name, blacklisted):
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
            log.exception("Exception when calling SendInBlue for email ({}) ContactsApi->create_contact: {}\n".format(email, e))


# TODO: update contact attributes upon completion of profile
# TODO: delete a contact and integrate with user retirement