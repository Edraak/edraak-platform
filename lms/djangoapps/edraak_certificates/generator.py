# -*- coding: utf-8 -*-
from datetime import datetime
import logging

from os import path
import re
from uuid import uuid4

from django.conf import settings
from django.core.files.temp import NamedTemporaryFile
from django.template.defaultfilters import date as _date
from django.utils import translation

from bidi.algorithm import get_display
import qrcode
from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import utils
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.colors import cyan
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from lms.djangoapps.certificates.models import GeneratedCertificate, CertificateStatuses
from courseware.access import has_access
from util import organizations_helpers as organization_api

from arabic_reshaper import ArabicReshaper

from lms.djangoapps.certificates.api import get_certificate_url, get_active_web_certificate


logger = logging.getLogger(__name__)
static_dir = path.join(path.dirname(__file__), 'assets')
fonts = {
    'Tajawal-Regular.ttf': 'tajawal Regular',
    'Tajawal-Bold.ttf': 'tajawal Bold',
}

for font_file, font_name in fonts.iteritems():
    font_path = path.join(static_dir, font_file)
    pdfmetrics.registerFont(TTFont(font_name, font_path, validate=True))


def text_to_bidi(text):
    text = normalize_spaces(text)
    configured_reshaper = ArabicReshaper(
        configuration={
            'use_unshaped_instead_of_isolated': True
        }
    )
    reshaped_text = configured_reshaper.reshape(text)
    bidi_text = get_display(reshaped_text)
    return bidi_text


def normalize_spaces(text):
    return re.sub(' +', ' ', text)


def contains_rtl_text(string):
    if not string:
        return False

    try:
        string.decode('ascii')
    except (UnicodeDecodeError, UnicodeEncodeError) as e:
        return True
    else:
        return False


def trans_digits(text):
    """
    This helper is responsible for returning digits in any text in
    Arabic–Indic numerals based on the site locale.
    :param text: The text that may have numerals.
    :return: A text with Arabic–Indic if the site in Arabic Locale,
             Arabic numerals if the site is running in English locale.
    """
    if text is None:
        return None
    if not isinstance(text, str) and not isinstance(text, unicode):
        return text
    # Translators: Enter the local format of the number e.g. ١، ٢، ٣
    return (
        text
        .replace('0', u'٠')
        .replace('1', u'١')
        .replace('2', u'٢')
        .replace('3', u'٣')
        .replace('4', u'٤')
        .replace('5', u'٥')
        .replace('6', u'٦')
        .replace('7', u'٧')
        .replace('8', u'٨')
        .replace('9', u'٩')
    )


class EdraakCertificate(object):
    def __init__(self, course, user, course_desc,
                 path_builder=None, preview_mode=None):
        self.course_id = course.id

        self.path_builder = path_builder
        self.certificate_data = get_active_web_certificate(
            course, preview_mode)
        self.cert = self._get_user_certificate(
            user, course, preview_mode=preview_mode)
        course_title_from_cert = self.certificate_data.get('course_title')
        self.course_name = course_title_from_cert if course_title_from_cert else course.display_name
        self.course_desc = course_desc
        self.organizations = organization_api.get_course_organizations(
            course_id=self.course_id)
        self.sponsors = None

        self.colors = {
            'base': (225 / 255.0, 0 / 255.0, 67 / 255.0),
            'grey-dark': (66 / 255.0, 74 / 255.0, 82 / 255.0),
            'grey-light': (113 / 255.0, 113 / 255.0, 113 / 255.0),
        }

        self.temp_file = NamedTemporaryFile(suffix='-cert.pdf')
        self.is_english = not contains_rtl_text(self.course_name)
        self.user_profile_name = self._get_user_name(user)

        self.left_panel_center = 1.6
        self.ctx = None
        self.size = None
        self.font = None
        self.font_size = None

    def _(self, text, method=False):
        """
        Force the translation language to match the course language instead of the platform language.
        """
        forced_language = 'en' if self.is_english else 'ar'
        with translation.override(forced_language):
            if method:
                return text
            return translation.ugettext(text)

    @staticmethod
    def _background_path():
        background_filename = 'certificate_layout.png'
        return path.join(static_dir, background_filename)

    @staticmethod
    def _get_user_certificate(user, course, preview_mode=None):
        """
        Retrieves user's certificate from db. Creates one in case of
        preview mode.
        Returns None if there is no certificate generated for given user
        otherwise returns `GeneratedCertificate` instance.
        """
        user_certificate = None
        if preview_mode:
            # certificate is being previewed from studio
            is_instructor = has_access(user, 'instructor', course)
            is_staff = has_access(user, 'staff', course)
            if is_instructor or is_staff:
                user_certificate = GeneratedCertificate(
                    mode=preview_mode, verify_uuid=unicode(uuid4().hex),
                    modified_date=datetime.now().date())
                logger.info('Downloading certificate for preview mode '
                            'requested by user %s for the course %s',
                            user, course.id)
        else:
            # certificate is being viewed by learner or public
            try:
                user_certificate = GeneratedCertificate.objects.get(
                    user=user, course_id=course.id,
                    status=CertificateStatuses.downloadable)
            except GeneratedCertificate.DoesNotExist:
                pass

        return user_certificate

    def _get_user_name(self, user):
        """
        Returns the user profile name if for teh requested
        certificate, if the user requested the english certificate
        and she doesn't fill the English name this should fall back
        to the Arabic one as it's mandatory
        """
        name_en = user.profile.name_en
        name_ar = user.profile.name

        if self.is_english and name_en:
            return name_en

        return name_ar

    def init_context(self):
        # Initializing the size of the background
        self.size = landscape(A4)

        ctx = canvas.Canvas(self.temp_file.name)
        ctx.setPageSize(self.size)
        self.ctx = ctx

    def bidi_x_axis(self, x, offset=0):
        """
        Normalize the X-axis and provide the correct RTL/LTR value.

        This helps avoiding hard-coded values for both directions.
        """
        if not self.is_english:
            return x - offset
        else:
            return self.size[0] - (x + offset)

    def add_certificate_bg(self):
        width, height = self.size
        background_path = self._background_path()

        self.ctx.drawImage(background_path, 0, 0, width, height)

    def _set_font(self, size, is_bold, color='grey-dark'):
        if is_bold:
            font = 'tajawal Bold'
        else:
            font = 'tajawal Regular'

        self.font = font
        self.font_size = size
        self.ctx.setFont(font, size)
        self.ctx.setFillColorRGB(*self.colors[color])

    def draw_single_line_bidi_text(self, text, x, y, size, bold=False, max_width=7.494, color='grey-dark'):
        x *= inch
        y *= inch
        size *= inch
        max_width *= inch

        text = text_to_bidi(text)

        while True:
            self._set_font(size, bold, color)
            lines = list(self._wrap_text(text, max_width))

            if len(lines) > 1:
                size *= 0.9  # reduce font size by 10%
            else:
                if not self.is_english:
                    self.ctx.drawRightString(self.bidi_x_axis(x), y, lines[0])
                else:
                    self.ctx.drawString(self.bidi_x_axis(x), y, lines[0])
                break

    def draw_bidi_center_text(self, text, x, y, size, bold=False, color='grey-dark'):
        x *= inch
        y *= inch
        size *= inch

        self._set_font(size, bold, color)

        text = text_to_bidi(text)

        self.ctx.drawCentredString(self.bidi_x_axis(x), y, text)

    def draw_english_text(self, text, x, y, size, bold=False, max_width=7.494, lh_factor=1.3):
        x *= inch
        y *= inch
        size *= inch
        max_width *= inch
        line_height = size * lh_factor
        self._set_font(size, bold)
        text = text_to_bidi(text)
        for line in self._wrap_text(text, max_width):
            self.ctx.drawString(self.bidi_x_axis(x), y, line)
            y -= line_height

    def draw_bidi_text(self, text, x, y, size, bold=False,
                       max_width=7.494, lh_factor=1.3, color='grey-dark'):
        x *= inch
        y *= inch
        size *= inch
        max_width *= inch
        line_height = size * lh_factor

        self._set_font(size, bold, color=color)

        text = text_to_bidi(text)

        for line in self._wrap_text(text, max_width):
            if not self.is_english:
                self.ctx.drawRightString(self.bidi_x_axis(x), y, line)
                y -= line_height
            else:
                self.ctx.drawString(self.bidi_x_axis(x), y, line)
                y -= line_height

    def add_course_org_logo(self):
        if not self.organizations:
            return

        # Fetch the organization data
        organization = self.organizations[0]
        organization_name = organization.get('name')

        logo = organization.get('logo', None)

        if not logo.name:
            return

        x = self.left_panel_center
        y = 5.9

        text = self._("Brought to you by")
        self.draw_bidi_center_text(text, x, y, 0.15, color='grey-light')

        # Underline the sentence
        text_width = stringWidth(text, self.font, self.font_size)
        length = text_width if self.is_english else -text_width
        xu = self.bidi_x_axis(x * inch, offset=length / 2.0)
        yu = (y - 0.1)*inch

        self.ctx.setStrokeColor(self.colors['grey-light'])
        self.ctx.setLineWidth(0.5)
        self.ctx.line(xu, yu, xu+length, yu)

        try:
            image = utils.ImageReader(self.path_builder(logo.url))
            iw, ih = image.getSize()
            aspect = iw / float(ih)
        except (IOError, ValueError):
            image = None
            iw, aspect = 0, 0

        height = inch
        width = height * aspect

        if aspect > 2: # in case the logo is too wide
            width = 2*inch
            height = width / aspect

        x = self.bidi_x_axis(x * inch, offset=width / 2.0)
        y -= 1.3

        self.ctx.drawImage(image, x, y*inch, width, height, mask='auto')

        x = self.left_panel_center
        y -= 0.15
        self.draw_bidi_center_text(
            organization_name, x, y, 0.09, color='grey-light')


    def add_course_sponsor_logo(self):
        if not self.sponsors:
            return

        x = self.left_panel_center
        y = 4.3

        text = self._("In Sponsorship with")
        self.draw_bidi_center_text(
            text, x, y, 0.125, color='grey-light')

        # Underline the sentence
        text_width = stringWidth(text, self.font, self.font_size)
        xu = self.bidi_x_axis(x * inch, offset=-text_width / 2.0)
        yu = (y - 0.1)*inch
        length = text_width if self.is_english else -text_width

        self.ctx.setStrokeColor(self.colors['grey-light'])
        self.ctx.setLineWidth(0.5)
        self.ctx.line(xu, yu, xu+length, yu)

        # Fetch the organization data
        organization = self.sponsors[0]
        logo = organization.get('logo', None)
        organization_name = organization.get('name')

        try:
            image = utils.ImageReader(self.path_builder(logo.url))
            iw, ih = image.getSize()
            aspect = iw / float(ih)
        except IOError:
            image = None
            iw, aspect = 0, 0

        height = inch / 2.1
        width = height * aspect

        x = self.bidi_x_axis(x * inch, offset=width / 2.0)
        y -= 0.7

        self.ctx.drawImage(image, x, y*inch, width, height, mask='auto')

        x = self.left_panel_center
        y -= 0.15
        self.draw_bidi_center_text(
            organization_name, x, y, 0.09, color='grey-light')

    def add_signatories(self):
        x = self.left_panel_center
        signature_space = 1.5
        space = 5

        if self.sponsors:
            space -= 1.13

        # Logo dimensions
        iw, ih = 180, 76
        aspect = iw / float(ih)
        height = inch / 1.9
        width = height * aspect
        signature_x = self.bidi_x_axis(x * inch, offset=width / 2.0)

        signatories = self.certificate_data.get('signatories', [])
        for signatory in signatories:
            signature = signatory['signature_image_path']
            signature_url = self.path_builder(signature)
            try:
                signature = ImageReader(signature_url)
            except IOError:
                logger.error('Cannot read signature %s', signature_url)
                continue

            space -= signature_space
            self.ctx.drawImage(
                signature, signature_x, (space+0.25)*inch,
                width, height, mask='auto')

            self.draw_bidi_center_text(
                signatory['name'], x, space, 0.15)
            self.draw_bidi_center_text(
                signatory['title'], x, space-0.15, 0.1,
                color='grey-light')
            self.draw_bidi_center_text(
                signatory['organization'], x, space-0.3, 0.1,
                color='grey-light')

    def add_edraak_logo(self):
        # Logo dimensions
        y = 6.5*inch
        logo = path.join(static_dir, 'edraak_logo.png')
        iw, ih = 471, 198
        aspect = iw / float(ih)

        height = inch - 10
        width = height * aspect

        x = self.left_panel_center
        logo_x = self.bidi_x_axis(x * inch, offset=width / 2.0)

        self.ctx.drawImage(logo, logo_x, y, width, height, mask='auto')

    def _wrap_text(self, text, max_width):
        same = lambda x: x
        _reversed = reversed if not self.is_english else same

        words = _reversed(text.split(u' '))

        def de_reverse(text_to_reverse):
            if not self.is_english:
                return u' '.join(_reversed(text_to_reverse.split(u' ')))
            else:
                return text_to_reverse

        line = u''
        for next_word in words:
            next_width = self.ctx.stringWidth(line.strip() + u' ' + next_word.strip())

            if next_width >= max_width:
                yield de_reverse(line).strip()
                line = next_word
            else:
                line += u' ' + next_word.strip()

        if line:
            yield de_reverse(line).strip()

    def save(self):
        self.ctx.showPage()
        self.ctx.save()

    def draw_debugging_grid(self):
        """
        This is draws a grid on the certificate if the platform
        running on a debug mode.
        """
        if not settings.DEBUG:
            return

        self.ctx.setStrokeColor(cyan) # put in a frame of reference
        xs = [x*inch for x in range(int(self.size[0]))]
        ys = [y*inch for y in range(int(self.size[1]))]
        self.ctx.grid(xs, ys)

    def add_certificate_footer(self):
        x, y = 11,  0.9
        sub_y = y - 0.25
        font_size = 0.15
        font_sub_size = 0.12

        if not self.is_english:
            date = trans_digits(_date(self.cert.modified_date, 'd F, Y'))
        else:
            date = self.cert.modified_date.strftime('%d %B, %Y')

        self.draw_bidi_text(
            self._('COURSE CERTIFICATE'), x, y, size=font_size)

        date_str = self._('Issued {date}').format(date=date)
        self.draw_bidi_text(
            date_str, x, sub_y, bold=True, size=font_sub_size)

        # Verification
        x = x - 3.3
        self.draw_bidi_text(
            self._('Verify the authenticity of this certificate at'),
            x, y, size=font_size)

        cert_url = get_certificate_url(
            course_id=self.course_id, uuid=self.cert.verify_uuid)

        url = self.path_builder(cert_url)
        cert_uuid = self.cert.verify_uuid

        qr_y = (y + sub_y)/2.0
        self.add_qr_code(url, x, qr_y)
        self.draw_bidi_text(cert_uuid, x, sub_y, size=font_sub_size)

        # Underline the UUID
        uuid_width = stringWidth(cert_uuid, self.font, self.font_size)
        xu = self.bidi_x_axis(x*inch)
        yu = (sub_y - 0.02)*inch
        length = uuid_width if self.is_english else -uuid_width

        self.ctx.setLineWidth(0.25)
        self.ctx.line(xu, yu, xu+length, yu)

        # Link the UUID
        rect = (xu, yu, xu+length, yu+(0.5*inch))
        self.ctx.linkURL(url, rect, relative=1)

    def add_qr_code(self, verification_url, x, y):
        height = inch/1.5
        border = 4
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=height,
            border=border,
        )
        qr.add_data(verification_url)
        qr.make(fit=True)
        qr_image = qr.make_image()
        image = utils.ImageReader(qr_image._img)

        iw, ih = image.getSize()
        aspect = iw / float(ih)
        width = height * aspect

        difference = width + border if self.is_english else 0
        x = self.bidi_x_axis(x * inch, offset=difference)
        y = y*inch - (height/2.25)

        self.ctx.drawImage(
            image, x, y, width, height, mask='auto')

    def generate_and_save(self):
        self.init_context()

        x = 11
        y = 7
        self.add_certificate_bg()

        # This debugging grid shows up when `settings.DEBUG = True`,
        # so don't worry about it in development, it'll go away in production
        self.draw_debugging_grid()

        self.add_edraak_logo()
        self.add_course_org_logo()
        self.add_course_sponsor_logo()
        self.add_signatories()

        self.draw_bidi_text(
            self._("CERTIFICATE OF COMPLETION"), x, y,
            size=0.30, color='base')

        y -= 0.5
        self.draw_bidi_text(
            self._("This is to certify that"), x, y,
            size=0.2, color='base')

        # User profile name
        name = self.user_profile_name
        user_profile_size = 0.42 if contains_rtl_text(name) else 0.55
        y -= 1.5

        self.draw_single_line_bidi_text(
            name, x, y,
            size=user_profile_size, bold=True)

        y -= 1
        self.draw_bidi_text(
            self._("Successfully completed"), x, y,
            size=0.2, color='grey-light')

        # Course Name
        name = self.course_name
        name_size = 0.31 if contains_rtl_text(name) else 0.3
        y -= 0.5
        self.draw_bidi_text(
            name, x, y, size=name_size, bold=True)

        y -= 0.5
        self.draw_bidi_text(
            self.course_desc, x, y, max_width=5.5, size=0.16)

        # Below goes the footer logic
        self.add_certificate_footer()
        self.save()
