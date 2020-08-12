"""
Utility functions for transcripts.
++++++++++++++++++++++++++++++++++
"""
from functools import wraps
from django.conf import settings
import os
import copy
import json
import requests
import logging
from pysrt import SubRipTime, SubRipItem, SubRipFile
from pysrt.srtexc import Error
from lxml import etree
from HTMLParser import HTMLParser
from six import text_type

from xmodule.exceptions import NotFoundError
from xmodule.contentstore.content import StaticContent
from xmodule.contentstore.django import contentstore

from .bumper_utils import get_bumper_settings

try:
    from edxval import api as edxval_api
except ImportError:
    edxval_api = None


log = logging.getLogger(__name__)

NON_EXISTENT_TRANSCRIPT = 'non_existent_dummy_file_name'


class TranscriptException(Exception):  # pylint: disable=missing-docstring
    pass


class TranscriptsGenerationException(Exception):  # pylint: disable=missing-docstring
    pass


class GetTranscriptsFromYouTubeException(Exception):  # pylint: disable=missing-docstring
    pass


class TranscriptsRequestValidationException(Exception):  # pylint: disable=missing-docstring
    pass


def exception_decorator(func):
    """
    Generate NotFoundError for TranscriptsGenerationException, UnicodeDecodeError.

    Args:
    `func`: Input function

    Returns:
    'wrapper': Decorated function
    """
    @wraps(func)
    def wrapper(*args, **kwds):
        try:
            return func(*args, **kwds)
        except (TranscriptsGenerationException, UnicodeDecodeError) as ex:
            log.exception(text_type(ex))
            raise NotFoundError
    return wrapper


def generate_subs(speed, source_speed, source_subs):
    """
    Generate transcripts from one speed to another speed.

    Args:
    `speed`: float, for this speed subtitles will be generated,
    `source_speed`: float, speed of source_subs
    `source_subs`: dict, existing subtitles for speed `source_speed`.

    Returns:
    `subs`: dict, actual subtitles.
    """
    if speed == source_speed:
        return source_subs

    coefficient = 1.0 * speed / source_speed
    subs = {
        'start': [
            int(round(timestamp * coefficient)) for
            timestamp in source_subs['start']
        ],
        'end': [
            int(round(timestamp * coefficient)) for
            timestamp in source_subs['end']
        ],
        'text': source_subs['text']}
    return subs


def save_to_store(content, name, mime_type, location):
    """
    Save named content to store by location.

    Returns location of saved content.
    """
    content_location = Transcript.asset_location(location, name)
    content = StaticContent(content_location, name, mime_type, content)
    contentstore().save(content)
    return content_location


def save_subs_to_store(subs, subs_id, item, language='en'):
    """
    Save transcripts into `StaticContent`.

    Args:
    `subs_id`: str, subtitles id
    `item`: video module instance
    `language`: two chars str ('uk'), language of translation of transcripts

    Returns: location of saved subtitles.
    """
    filedata = json.dumps(subs, indent=2)
    filename = subs_filename(subs_id, language)
    return save_to_store(filedata, filename, 'application/json', item.location)


def youtube_video_transcript_name(youtube_text_api):
    """
    Get the transcript name from available transcripts of video
    with respect to language from youtube server
    """
    utf8_parser = etree.XMLParser(encoding='utf-8')

    transcripts_param = {'type': 'list', 'v': youtube_text_api['params']['v']}
    lang = youtube_text_api['params']['lang']
    # get list of transcripts of specific video
    # url-form
    # http://video.google.com/timedtext?type=list&v={VideoId}
    youtube_response = requests.get('http://' + youtube_text_api['url'], params=transcripts_param)
    if youtube_response.status_code == 200 and youtube_response.text:
        youtube_data = etree.fromstring(youtube_response.content, parser=utf8_parser)
        # iterate all transcripts information from youtube server
        for element in youtube_data:
            # search specific language code such as 'en' in transcripts info list
            if element.tag == 'track' and element.get('lang_code', '') == lang:
                return element.get('name')
    return None


def get_transcripts_from_youtube(youtube_id, settings, i18n, youtube_transcript_name=''):
    """
    Gets transcripts from youtube for youtube_id.

    Parses only utf-8 encoded transcripts.
    Other encodings are not supported at the moment.

    Returns (status, transcripts): bool, dict.
    """
    _ = i18n.ugettext

    utf8_parser = etree.XMLParser(encoding='utf-8')

    youtube_text_api = copy.deepcopy(settings.YOUTUBE['TEXT_API'])
    youtube_text_api['params']['v'] = youtube_id
    # if the transcript name is not empty on youtube server we have to pass
    # name param in url in order to get transcript
    # example http://video.google.com/timedtext?lang=en&v={VideoId}&name={transcript_name}
    youtube_transcript_name = youtube_video_transcript_name(youtube_text_api)
    if youtube_transcript_name:
        youtube_text_api['params']['name'] = youtube_transcript_name
    data = requests.get('http://' + youtube_text_api['url'], params=youtube_text_api['params'])

    if data.status_code != 200 or not data.text:
        msg = _("Can't receive transcripts from Youtube for {youtube_id}. Status code: {status_code}.").format(
            youtube_id=youtube_id,
            status_code=data.status_code
        )
        raise GetTranscriptsFromYouTubeException(msg)

    sub_starts, sub_ends, sub_texts = [], [], []
    xmltree = etree.fromstring(data.content, parser=utf8_parser)
    for element in xmltree:
        if element.tag == "text":
            start = float(element.get("start"))
            duration = float(element.get("dur", 0))  # dur is not mandatory
            text = element.text
            end = start + duration

            if text:
                # Start and end should be ints representing the millisecond timestamp.
                sub_starts.append(int(start * 1000))
                sub_ends.append(int((end + 0.0001) * 1000))
                sub_texts.append(text.replace('\n', ' '))

    return {'start': sub_starts, 'end': sub_ends, 'text': sub_texts}


def download_youtube_subs(youtube_id, video_descriptor, settings):
    """
    Download transcripts from Youtube.

    Args:
        youtube_id: str, actual youtube_id of the video.
        video_descriptor: video descriptor instance.

    We save transcripts for 1.0 speed, as for other speed conversion is done on front-end.

    Returns:
        Serialized sjson transcript content, if transcripts were successfully downloaded and saved.

    Raises:
        GetTranscriptsFromYouTubeException, if fails.
    """
    i18n = video_descriptor.runtime.service(video_descriptor, "i18n")
    _ = i18n.ugettext

    subs = get_transcripts_from_youtube(youtube_id, settings, i18n)
    return json.dumps(subs, indent=2)


def remove_subs_from_store(subs_id, item, lang='en'):
    """
    Remove from store, if transcripts content exists.
    """
    filename = subs_filename(subs_id, lang)
    Transcript.delete_asset(item.location, filename)


def generate_subs_from_source(speed_subs, subs_type, subs_filedata, item, language='en'):
    """Generate transcripts from source files (like SubRip format, etc.)
    and save them to assets for `item` module.
    We expect, that speed of source subs equal to 1

    :param speed_subs: dictionary {speed: sub_id, ...}
    :param subs_type: type of source subs: "srt", ...
    :param subs_filedata:unicode, content of source subs.
    :param item: module object.
    :param language: str, language of translation of transcripts
    :returns: True, if all subs are generated and saved successfully.
    """
    _ = item.runtime.service(item, "i18n").ugettext
    if subs_type.lower() != 'srt':
        raise TranscriptsGenerationException(_("We support only SubRip (*.srt) transcripts format."))
    try:
        srt_subs_obj = SubRipFile.from_string(subs_filedata)
    except Exception as ex:
        msg = _("Something wrong with SubRip transcripts file during parsing. Inner message is {error_message}").format(
            error_message=text_type(ex)
        )
        raise TranscriptsGenerationException(msg)
    if not srt_subs_obj:
        raise TranscriptsGenerationException(_("Something wrong with SubRip transcripts file during parsing."))

    sub_starts = []
    sub_ends = []
    sub_texts = []

    for sub in srt_subs_obj:
        sub_starts.append(sub.start.ordinal)
        sub_ends.append(sub.end.ordinal)
        sub_texts.append(sub.text.replace('\n', ' '))

    subs = {
        'start': sub_starts,
        'end': sub_ends,
        'text': sub_texts}

    for speed, subs_id in speed_subs.iteritems():
        save_subs_to_store(
            generate_subs(speed, 1, subs),
            subs_id,
            item,
            language
        )

    return subs


def generate_srt_from_sjson(sjson_subs, speed):
    """Generate transcripts with speed = 1.0 from sjson to SubRip (*.srt).

    :param sjson_subs: "sjson" subs.
    :param speed: speed of `sjson_subs`.
    :returns: "srt" subs.
    """

    output = ''

    equal_len = len(sjson_subs['start']) == len(sjson_subs['end']) == len(sjson_subs['text'])
    if not equal_len:
        return output

    sjson_speed_1 = generate_subs(speed, 1, sjson_subs)

    for i in range(len(sjson_speed_1['start'])):
        item = SubRipItem(
            index=i,
            start=SubRipTime(milliseconds=sjson_speed_1['start'][i]),
            end=SubRipTime(milliseconds=sjson_speed_1['end'][i]),
            text=sjson_speed_1['text'][i]
        )
        output += (unicode(item))
        output += '\n'
    return output


def generate_sjson_from_srt(srt_subs):
    """
    Generate transcripts from sjson to SubRip (*.srt).

    Arguments:
        srt_subs(SubRip): "SRT" subs object

    Returns:
        Subs converted to "SJSON" format.
    """
    sub_starts = []
    sub_ends = []
    sub_texts = []
    for sub in srt_subs:
        sub_starts.append(sub.start.ordinal)
        sub_ends.append(sub.end.ordinal)
        sub_texts.append(sub.text.replace('\n', ' '))

    sjson_subs = {
        'start': sub_starts,
        'end': sub_ends,
        'text': sub_texts
    }
    return sjson_subs


def copy_or_rename_transcript(new_name, old_name, item, delete_old=False, user=None):
    """
    Renames `old_name` transcript file in storage to `new_name`.

    If `old_name` is not found in storage, raises `NotFoundError`.
    If `delete_old` is True, removes `old_name` files from storage.
    """
    filename = u'subs_{0}.srt.sjson'.format(old_name)
    content_location = StaticContent.compute_location(item.location.course_key, filename)
    transcripts = contentstore().find(content_location).data
    save_subs_to_store(json.loads(transcripts), new_name, item)
    item.sub = new_name
    item.save_with_metadata(user)
    if delete_old:
        remove_subs_from_store(old_name, item)


def get_html5_ids(html5_sources):
    """
    Helper method to parse out an HTML5 source into the ideas
    NOTE: This assumes that '/' are not in the filename
    """
    html5_ids = [x.split('/')[-1].rsplit('.', 1)[0] for x in html5_sources]
    return html5_ids


def manage_video_subtitles_save(item, user, old_metadata=None, generate_translation=False):
    """
    Does some specific things, that can be done only on save.

    Video player item has some video fields: HTML5 ones and Youtube one.

    If value of `sub` field of `new_item` is cleared, transcripts should be removed.

    `item` is video module instance with updated values of fields,
    but actually have not been saved to store yet.

    `old_metadata` contains old values of XFields.

    # 1.
    If value of `sub` field of `new_item` is different from values of video fields of `new_item`,
    and `new_item.sub` file is present, then code in this function creates copies of
    `new_item.sub` file with new names. That names are equal to values of video fields of `new_item`
    After that `sub` field of `new_item` is changed to one of values of video fields.
    This whole action ensures that after user changes video fields, proper `sub` files, corresponding
    to new values of video fields, will be presented in system.

    # 2. convert /static/filename.srt  to filename.srt in self.transcripts.
    (it is done to allow user to enter both /static/filename.srt and filename.srt)

    # 3. Generate transcripts translation only  when user clicks `save` button, not while switching tabs.
    a) delete sjson translation for those languages, which were removed from `item.transcripts`.
        Note: we are not deleting old SRT files to give user more flexibility.
    b) For all SRT files in`item.transcripts` regenerate new SJSON files.
        (To avoid confusing situation if you attempt to correct a translation by uploading
        a new version of the SRT file with same name).
    """
    _ = item.runtime.service(item, "i18n").ugettext

    # # 1.
    # html5_ids = get_html5_ids(item.html5_sources)

    # # Youtube transcript source should always have a higher priority than html5 sources. Appending
    # # `youtube_id_1_0` at the end helps achieve this when we read transcripts list.
    # possible_video_id_list = html5_ids + [item.youtube_id_1_0]
    # sub_name = item.sub
    # for video_id in possible_video_id_list:
    #     if not video_id:
    #         continue
    #     if not sub_name:
    #         remove_subs_from_store(video_id, item)
    #         continue
    #     # copy_or_rename_transcript changes item.sub of module
    #     try:
    #         # updates item.sub with `video_id`, if it is successful.
    #         copy_or_rename_transcript(video_id, sub_name, item, user=user)
    #     except NotFoundError:
    #         # subtitles file `sub_name` is not presented in the system. Nothing to copy or rename.
    #         log.debug(
    #             "Copying %s file content to %s name is failed, "
    #             "original file does not exist.",
    #             sub_name, video_id
    #         )

    # 2.
    if generate_translation:
        for lang, filename in item.transcripts.items():
            item.transcripts[lang] = os.path.split(filename)[-1]

    # 3.
    if generate_translation:
        old_langs = set(old_metadata.get('transcripts', {})) if old_metadata else set()
        new_langs = set(item.transcripts)

        html5_ids = get_html5_ids(item.html5_sources)
        possible_video_id_list = html5_ids + [item.youtube_id_1_0]

        for lang in old_langs.difference(new_langs):  # 3a
            for video_id in possible_video_id_list:
                if video_id:
                    remove_subs_from_store(video_id, item, lang)

        reraised_message = ''
        for lang in new_langs:  # 3b
            try:
                generate_sjson_for_all_speeds(
                    item,
                    item.transcripts[lang],
                    {speed: subs_id for subs_id, speed in youtube_speed_dict(item).iteritems()},
                    lang,
                )
            except TranscriptException as ex:
                pass
        if reraised_message:
            item.save_with_metadata(user)
            raise TranscriptException(reraised_message)


def youtube_speed_dict(item):
    """
    Returns {speed: youtube_ids, ...} dict for existing youtube_ids
    """
    yt_ids = [item.youtube_id_0_75, item.youtube_id_1_0, item.youtube_id_1_25, item.youtube_id_1_5]
    yt_speeds = [0.75, 1.00, 1.25, 1.50]
    youtube_ids = {p[0]: p[1] for p in zip(yt_ids, yt_speeds) if p[0]}
    return youtube_ids


def subs_filename(subs_id, lang='en'):
    """
    Generate proper filename for storage.
    """
    if lang == 'en':
        return u'subs_{0}.srt.sjson'.format(subs_id)
    else:
        return u'{0}_subs_{1}.srt.sjson'.format(lang, subs_id)


def generate_sjson_for_all_speeds(item, user_filename, result_subs_dict, lang):
    """
    Generates sjson from srt for given lang.

    `item` is module object.
    """
    _ = item.runtime.service(item, "i18n").ugettext

    try:
        srt_transcripts = contentstore().find(Transcript.asset_location(item.location, user_filename))
    except NotFoundError as ex:
        raise TranscriptException(_("{exception_message}: Can't find uploaded transcripts: {user_filename}").format(
            exception_message=text_type(ex),
            user_filename=user_filename
        ))

    if not lang:
        lang = item.transcript_language

    # Used utf-8-sig encoding type instead of utf-8 to remove BOM(Byte Order Mark), e.g. U+FEFF
    generate_subs_from_source(
        result_subs_dict,
        os.path.splitext(user_filename)[1][1:],
        srt_transcripts.data.decode('utf-8-sig'),
        item,
        lang
    )


def get_or_create_sjson(item, transcripts):
    """
    Get sjson if already exists, otherwise generate it.

    Generate sjson with subs_id name, from user uploaded srt.
    Subs_id is extracted from srt filename, which was set by user.

    Args:
        transcipts (dict): dictionary of (language: file) pairs.

    Raises:
        TranscriptException: when srt subtitles do not exist,
        and exceptions from generate_subs_from_source.

    `item` is module object.
    """
    user_filename = transcripts[item.transcript_language]
    user_subs_id = os.path.splitext(user_filename)[0]
    source_subs_id, result_subs_dict = user_subs_id, {1.0: user_subs_id}
    try:
        sjson_transcript = Transcript.asset(item.location, source_subs_id, item.transcript_language).data
    except NotFoundError:  # generating sjson from srt
        generate_sjson_for_all_speeds(item, user_filename, result_subs_dict, item.transcript_language)
    sjson_transcript = Transcript.asset(item.location, source_subs_id, item.transcript_language).data
    return sjson_transcript


def get_video_ids_info(edx_video_id, youtube_id_1_0, html5_sources):
    """
    Returns list internal or external video ids.

    Arguments:
        edx_video_id (unicode): edx_video_id
        youtube_id_1_0 (unicode): youtube id
        html5_sources (list): html5 video ids

    Returns:
        tuple: external or internal, video ids list
    """
    clean = lambda item: item.strip() if isinstance(item, basestring) else item
    external = not bool(clean(edx_video_id))

    video_ids = [edx_video_id, youtube_id_1_0] + get_html5_ids(html5_sources)

    # video_ids cleanup
    video_ids = filter(lambda item: bool(clean(item)), video_ids)

    return external, video_ids


def clean_video_id(edx_video_id):
    """
    Cleans an edx video ID.

    Arguments:
        edx_video_id(unicode): edx-val's video identifier
    """
    return edx_video_id and edx_video_id.strip()


def get_video_transcript_content(edx_video_id, language_code):
    """
    Gets video transcript content, only if the corresponding feature flag is enabled for the given `course_id`.

    Arguments:
        language_code(unicode): Language code of the requested transcript
        edx_video_id(unicode): edx-val's video identifier

    Returns:
        A dict containing transcript's file name and its sjson content.
    """
    transcript = None
    edx_video_id = clean_video_id(edx_video_id)
    if edxval_api and edx_video_id:
        transcript = edxval_api.get_video_transcript_data(edx_video_id, language_code)

    return transcript


def get_available_transcript_languages(edx_video_id):
    """
    Gets available transcript languages for a video.

    Arguments:
        edx_video_id(unicode): edx-val's video identifier

    Returns:
        A list containing distinct transcript language codes against all the passed video ids.
    """
    available_languages = []
    edx_video_id = clean_video_id(edx_video_id)
    if edxval_api and edx_video_id:
        available_languages = edxval_api.get_available_transcript_languages(video_id=edx_video_id)

    return available_languages


def convert_video_transcript(file_name, content, output_format):
    """
    Convert video transcript into desired format

    Arguments:
        file_name: name of transcript file along with its extension
        content: transcript content stream
        output_format: the format in which transcript will be converted

    Returns:
        A dict containing the new transcript filename and the content converted into desired format.
    """
    name_and_extension = os.path.splitext(file_name)
    basename, input_format = name_and_extension[0], name_and_extension[1][1:]
    filename = u'{base_name}.{ext}'.format(base_name=basename, ext=output_format)
    converted_transcript = Transcript.convert(content, input_format=input_format, output_format=output_format)

    return dict(filename=filename, content=converted_transcript)


class Transcript(object):
    """
    Container for transcript methods.
    """
    SRT = 'srt'
    TXT = 'txt'
    SJSON = 'sjson'
    mime_types = {
        SRT: 'application/x-subrip; charset=utf-8',
        TXT: 'text/plain; charset=utf-8',
        SJSON: 'application/json',
    }

    @staticmethod
    def convert(content, input_format, output_format):
        """
        Convert transcript `content` from `input_format` to `output_format`.

        Accepted input formats: sjson, srt.
        Accepted output format: srt, txt, sjson.

        Raises:
            TranscriptsGenerationException: On parsing the invalid srt content during conversion from srt to sjson.
        """
        assert input_format in ('srt', 'sjson')
        assert output_format in ('txt', 'srt', 'sjson')

        if input_format == output_format:
            return content

        if input_format == 'srt':

            if output_format == 'txt':
                text = SubRipFile.from_string(content.decode('utf8')).text
                return HTMLParser().unescape(text)

            elif output_format == 'sjson':
                try:
                    # With error handling (set to 'ERROR_RAISE'), we will be getting
                    # the exception if something went wrong in parsing the transcript.
                    srt_subs = SubRipFile.from_string(
                        # Skip byte order mark(BOM) character
                        content.decode('utf-8-sig'),
                        error_handling=SubRipFile.ERROR_RAISE
                    )
                except Error as ex:   # Base exception from pysrt
                    raise TranscriptsGenerationException(text_type(ex))

                return json.dumps(generate_sjson_from_srt(srt_subs))

        if input_format == 'sjson':

            if output_format == 'txt':
                text = json.loads(content)['text']
                return HTMLParser().unescape("\n".join(text))

            elif output_format == 'srt':
                return generate_srt_from_sjson(json.loads(content), speed=1.0)

    @staticmethod
    def asset(location, subs_id, lang='en', filename=None):
        """
        Get asset from contentstore, asset location is built from subs_id and lang.

        `location` is module location.
        """
        # HACK Warning! this is temporary and will be removed once edx-val take over the
        # transcript module and contentstore will only function as fallback until all the
        # data is migrated to edx-val. It will be saving a contentstore hit for a hardcoded
        # dummy-non-existent-transcript name.
        if NON_EXISTENT_TRANSCRIPT in [subs_id, filename]:
            raise NotFoundError

        asset_filename = subs_filename(subs_id, lang) if not filename else filename
        return Transcript.get_asset(location, asset_filename)

    @staticmethod
    def get_asset(location, filename):
        """
        Return asset by location and filename.
        """
        return contentstore().find(Transcript.asset_location(location, filename))

    @staticmethod
    def asset_location(location, filename):
        """
        Return asset location. `location` is module location.
        """
        # If user transcript filename is empty, raise `TranscriptException` to avoid `InvalidKeyError`.
        if not filename:
            raise TranscriptException("Transcript not uploaded yet")
        return StaticContent.compute_location(location.course_key, filename)

    @staticmethod
    def delete_asset(location, filename):
        """
        Delete asset by location and filename.
        """
        try:
            contentstore().delete(Transcript.asset_location(location, filename))
            log.info("Transcript asset %s was removed from store.", filename)
        except NotFoundError:
            pass
        return StaticContent.compute_location(location.course_key, filename)


class VideoTranscriptsMixin(object):
    """Mixin class for transcript functionality.

    This is necessary for both VideoModule and VideoDescriptor.
    """

    def available_translations(self, transcripts, verify_assets=None, is_bumper=False):
        """
        Return a list of language codes for which we have transcripts.

        Arguments:
            verify_assets (boolean): If True, checks to ensure that the transcripts
                really exist in the contentstore. If False, we just look at the
                VideoDescriptor fields and do not query the contentstore. One reason
                we might do this is to avoid slamming contentstore() with queries
                when trying to make a listing of videos and their languages.

                Defaults to `not FALLBACK_TO_ENGLISH_TRANSCRIPTS`.

            transcripts (dict): A dict with all transcripts and a sub.
            include_val_transcripts(boolean): If True, adds the edx-val transcript languages as well.
        """
        translations = []
        if verify_assets is None:
            verify_assets = not settings.FEATURES.get('FALLBACK_TO_ENGLISH_TRANSCRIPTS')

        sub, other_langs = transcripts["sub"], transcripts["transcripts"]

        if verify_assets:
            all_langs = dict(**other_langs)
            if sub:
                all_langs.update({'en': sub})

            for language, filename in all_langs.iteritems():
                try:
                    # for bumper videos, transcripts are stored in content store only
                    if is_bumper:
                        get_transcript_for_video(self.location, filename, filename, language)
                    else:
                        get_transcript(self, language)
                except NotFoundError:
                    continue

                translations.append(language)
        else:
            # If we're not verifying the assets, we just trust our field values
            translations = list(other_langs)
            if not translations or sub:
                translations += ['en']

        # to clean redundant language codes.
        return list(set(translations))

    def get_transcript(self, transcripts, transcript_format='srt', lang=None):
        """
        Returns transcript, filename and MIME type.

        transcripts (dict): A dict with all transcripts and a sub.

        Raises:
            - NotFoundError if cannot find transcript file in storage.
            - ValueError if transcript file is empty or incorrect JSON.
            - KeyError if transcript file has incorrect format.

        If language is 'en', self.sub should be correct subtitles name.
        If language is 'en', but if self.sub is not defined, this means that we
        should search for video name in order to get proper transcript (old style courses).
        If language is not 'en', give back transcript in proper language and format.
        """
        if not lang:
            lang = self.get_default_transcript_language(transcripts)

        sub, other_lang = transcripts["sub"], transcripts["transcripts"]
        if lang == 'en':
            if sub:  # HTML5 case and (Youtube case for new style videos)
                transcript_name = sub
            elif self.youtube_id_1_0:  # old courses
                transcript_name = self.youtube_id_1_0
            else:
                log.debug("No subtitles for 'en' language")
                raise ValueError

            data = Transcript.asset(self.location, transcript_name, lang).data
            filename = u'{}.{}'.format(transcript_name, transcript_format)
            content = Transcript.convert(data, 'sjson', transcript_format)
        else:
            data = Transcript.asset(self.location, None, None, other_lang[lang]).data
            filename = u'{}.{}'.format(os.path.splitext(other_lang[lang])[0], transcript_format)
            content = Transcript.convert(data, 'srt', transcript_format)

        if not content:
            log.debug('no subtitles produced in get_transcript')
            raise ValueError

        return content, filename, Transcript.mime_types[transcript_format]

    def get_default_transcript_language(self, transcripts):
        """
        Returns the default transcript language for this video module.

        Args:
            transcripts (dict): A dict with all transcripts and a sub.
        """
        sub, other_lang = transcripts["sub"], transcripts["transcripts"]
        if self.transcript_language in other_lang:
            transcript_language = self.transcript_language
        elif sub:
            transcript_language = u'en'
        elif len(other_lang) > 0:
            transcript_language = sorted(other_lang)[0]
        else:
            transcript_language = u'en'
        return transcript_language

    def get_transcripts_info(self, is_bumper=False):
        """
        Returns a transcript dictionary for the video.

        Arguments:
            is_bumper(bool): If True, the request is for the bumper transcripts
            include_val_transcripts(bool): If True, include edx-val transcripts as well
        """
        if is_bumper:
            transcripts = copy.deepcopy(get_bumper_settings(self).get('transcripts', {}))
            sub = transcripts.pop("en", "")
        else:
            transcripts = self.transcripts if self.transcripts else {}
            sub = self.sub

        # Only attach transcripts that are not empty.
        transcripts = {
            language_code: transcript_file
            for language_code, transcript_file in transcripts.items() if transcript_file != ''
        }

        # bumper transcripts are stored in content store so we don't need to include val transcripts
        if not is_bumper:
            transcript_languages = get_available_transcript_languages(edx_video_id=self.edx_video_id)
            # HACK Warning! this is temporary and will be removed once edx-val take over the
            # transcript module and contentstore will only function as fallback until all the
            # data is migrated to edx-val.
            for language_code in transcript_languages:
                if language_code == 'en' and not sub:
                    sub = NON_EXISTENT_TRANSCRIPT
                elif not transcripts.get(language_code):
                    transcripts[language_code] = NON_EXISTENT_TRANSCRIPT

        return {
            "sub": sub,
            "transcripts": transcripts,
        }


@exception_decorator
def get_transcript_from_val(edx_video_id, lang=None, output_format=Transcript.SRT):
    """
    Get video transcript from edx-val.
    Arguments:
        edx_video_id (unicode): video identifier
        lang (unicode): transcript language
        output_format (unicode): transcript output format
    Returns:
        tuple containing content, filename, mimetype
    """
    transcript = get_video_transcript_content(edx_video_id, lang)
    if not transcript:
        raise NotFoundError(u'Transcript not found for {}, lang: {}'.format(edx_video_id, lang))

    transcript_conversion_props = dict(transcript, output_format=output_format)
    transcript = convert_video_transcript(**transcript_conversion_props)
    filename = transcript['filename']
    content = transcript['content']
    mimetype = Transcript.mime_types[output_format]

    return content, filename, mimetype


def get_transcript_for_video(video_location, subs_id, file_name, language):
    """
    Get video transcript from content store.

    NOTE: Transcripts can be searched from content store by two ways:
    1. by an id(a.k.a subs_id) which will be used to construct transcript filename
    2. by providing transcript filename

    Arguments:
        video_location (Locator): Video location
        subs_id (unicode): id for a transcript in content store
        file_name (unicode): file_name for a transcript in content store
        language (unicode): transcript language

    Returns:
        tuple containing transcript input_format, basename, content
    """
    try:
        if subs_id is None:
            raise NotFoundError
        content = Transcript.asset(video_location, subs_id, language).data
        base_name = subs_id
        input_format = Transcript.SJSON
    except NotFoundError:
        content = Transcript.asset(video_location, None, language, file_name).data
        base_name = os.path.splitext(file_name)[0]
        input_format = Transcript.SRT

    return input_format, base_name, content


@exception_decorator
def get_transcript_from_contentstore(video, language, output_format, transcripts_info, youtube_id=None):
    """
    Get video transcript from content store.

    Arguments:
        video (Video Descriptor): Video descriptor
        language (unicode): transcript language
        output_format (unicode): transcript output format
        transcripts_info (dict): transcript info for a video
        youtube_id (unicode): youtube video id

    Returns:
        tuple containing content, filename, mimetype
    """
    input_format, base_name, transcript_content = None, None, None
    if output_format not in (Transcript.SRT, Transcript.SJSON, Transcript.TXT):
        raise NotFoundError('Invalid transcript format `{output_format}`'.format(output_format=output_format))

    sub, other_languages = transcripts_info['sub'], transcripts_info['transcripts']
    transcripts = dict(other_languages)

    # this is sent in case of a translation dispatch and we need to use it as our subs_id.
    possible_sub_ids = [youtube_id, sub, video.youtube_id_1_0] + get_html5_ids(video.html5_sources)
    for sub_id in possible_sub_ids:
        try:
            transcripts[u'en'] = sub_id
            input_format, base_name, transcript_content = get_transcript_for_video(
                video.location,
                subs_id=sub_id,
                file_name=transcripts[language],
                language=language
            )
            break
        except (KeyError, NotFoundError):
            continue

    if transcript_content is None:
        raise NotFoundError('No transcript for `{lang}` language'.format(
            lang=language
        ))

    # add language prefix to transcript file only if language is not None
    language_prefix = '{}_'.format(language) if language else ''
    transcript_name = u'{}{}.{}'.format(language_prefix, base_name, output_format)
    transcript_content = Transcript.convert(transcript_content, input_format=input_format, output_format=output_format)
    if not transcript_content.strip():
        raise NotFoundError('No transcript content')

    if youtube_id:
        youtube_ids = youtube_speed_dict(video)
        transcript_content = json.dumps(
            generate_subs(youtube_ids.get(youtube_id, 1), 1, json.loads(transcript_content))
        )

    return transcript_content, transcript_name, Transcript.mime_types[output_format]


def get_transcript(video, lang=None, output_format=Transcript.SRT, youtube_id=None):
    """
    Get video transcript from edx-val or content store.

    Arguments:
        video (Video Descriptor): Video Descriptor
        lang (unicode): transcript language
        output_format (unicode): transcript output format
        youtube_id (unicode): youtube video id

    Returns:
        tuple containing content, filename, mimetype
    """
    transcripts_info = video.get_transcripts_info()
    if not lang:
        lang = video.get_default_transcript_language(transcripts_info)

    try:
        edx_video_id = clean_video_id(video.edx_video_id)
        if not edx_video_id:
            raise NotFoundError
        return get_transcript_from_val(edx_video_id, lang, output_format)
    except NotFoundError:
        return get_transcript_from_contentstore(
            video,
            lang,
            youtube_id=youtube_id,
            output_format=output_format,
            transcripts_info=transcripts_info
        )
