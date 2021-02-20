"""
Copy of edx_ace/channel/django_email.py with an amendment to add file attachment
(to avoid customizing edx-ace repo. And to keep using ace templates, not django rendering)
"""
import re
from smtplib import SMTPException

import six

from edx_ace import delivery, policy, presentation
from edx_ace.channel import get_channel_for_message, Channel, ChannelType
from edx_ace.channel.django_email import DjangoEmailChannel, TEMPLATE, LOG
from edx_ace.errors import ChannelError, UnsupportedChannelError, FatalChannelDeliveryError
from django.conf import settings
from django.core.mail import EmailMultiAlternatives


class DjangoEmailChannelWithAttachement(Channel):
    channel_type = ChannelType.EMAIL
    def __init__(self):
        super(DjangoEmailChannelWithAttachement, self).__init__()
        self.attachment_data = None
        self.attachment_name = None
        self.attachment_type = None

    @classmethod
    def enabled(cls):
        return True

    def deliver(self, message, rendered_message):
        # Compress spaces and remove newlines to make it easier to author templates.
        subject = re.sub('\\s+', ' ', rendered_message.subject, re.UNICODE).strip()
        default_from_address = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        reply_to = message.options.get('reply_to', None)
        from_address = message.options.get('from_address', default_from_address)
        if not from_address:
            raise FatalChannelDeliveryError(
                'from_address must be included in message delivery options or as the DEFAULT_FROM_EMAIL settings'
            )

        rendered_template = TEMPLATE.format(
            head_html=rendered_message.head_html,
            body_html=rendered_message.body_html,
        )
        try:
            mail = EmailMultiAlternatives(
                subject=subject,
                body=rendered_message.body,
                from_email=from_address,
                to=[message.recipient.email_address],
                reply_to=reply_to,
            )

            mail.attach_alternative(rendered_template, 'text/html')
            if self.attachment_name and self.attachment_data and self.attachment_type:
                mail.attach(self.attachment_name, self.attachment_data, self.attachment_type)
            mail.send()
        except SMTPException as e:
            LOG.exception(e)
            raise FatalChannelDeliveryError(u'An SMTP error occurred (and logged) from Django send_email()')


def send_with_file(msg, attachment_name, attachment_data, attachment_type):
    msg.report_basics()

    channels_for_message = policy.channels_for(msg)

    for channel_type in channels_for_message:
        try:
            channel = get_channel_for_message(channel_type, msg)
        except UnsupportedChannelError:
            continue

        try:
            rendered_message = presentation.render(channel, msg)
            if isinstance(channel, DjangoEmailChannel):
                channel = DjangoEmailChannelWithAttachement()
                channel.attachment_data = attachment_data
                channel.attachment_name = attachment_name
                channel.attachment_type = attachment_type
            delivery.deliver(channel, rendered_message, msg)
        except ChannelError as error:
            msg.report(
                u'{channel_type}_error'.format(channel_type=channel_type),
                six.text_type(error)
            )
