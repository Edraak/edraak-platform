from django.conf import settings

import sib_api_v3_sdk


def setup_sendinblue_configuration():
    configuration = None

    if hasattr(settings, "EDRAAK_SENDINBLUE_API_KEY") and settings.EDRAAK_SENDINBLUE_API_KEY:
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.EDRAAK_SENDINBLUE_API_KEY

    return configuration
