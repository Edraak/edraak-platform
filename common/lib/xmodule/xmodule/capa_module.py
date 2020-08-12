"""Implements basics of Capa, including class CapaModule."""
import json
import logging
import re
import sys

from lxml import etree
from pkg_resources import resource_string

from capa import responsetypes
from xmodule.exceptions import NotFoundError, ProcessingError
from xmodule.raw_module import RawDescriptor
from xmodule.contentstore.django import contentstore
from xmodule.util.misc import escape_html_characters
from xmodule.util.sandboxing import get_python_lib_zip
from xmodule.x_module import DEPRECATION_VSCOMPAT_EVENT, XModule, module_attr

from .capa_base import CapaFields, CapaMixin, ComplexEncoder

log = logging.getLogger("edx.courseware")


class CapaModule(CapaMixin, XModule):
    """
    An XModule implementing LonCapa format problems, implemented by way of
    capa.capa_problem.LoncapaProblem

    CapaModule.__init__ takes the same arguments as xmodule.x_module:XModule.__init__
    """
    icon_class = 'problem'

    js = {
        'js': [
            resource_string(__name__, 'js/src/javascript_loader.js'),
            resource_string(__name__, 'js/src/capa/display.js'),
            resource_string(__name__, 'js/src/collapsible.js'),
            resource_string(__name__, 'js/src/capa/imageinput.js'),
            resource_string(__name__, 'js/src/capa/schematic.js'),
        ]
    }

    js_module_name = "Problem"
    css = {'scss': [resource_string(__name__, 'css/capa/display.scss')]}

    def author_view(self, context):
        """
        Renders the Studio preview view.
        """
        return self.student_view(context)

    def handle_ajax(self, dispatch, data):
        """
        This is called by courseware.module_render, to handle an AJAX call.

        `data` is request.POST.

        Returns a json dictionary:
        { 'progress_changed' : True/False,
          'progress' : 'none'/'in_progress'/'done',
          <other request-specific values here > }
        """
        handlers = {
            'hint_button': self.hint_button,
            'problem_get': self.get_problem,
            'problem_check': self.submit_problem,
            'problem_reset': self.reset_problem,
            'problem_save': self.save_problem,
            'problem_show': self.get_answer,
            'score_update': self.update_score,
            'input_ajax': self.handle_input_ajax,
            'ungraded_response': self.handle_ungraded_response
        }

        _ = self.runtime.service(self, "i18n").ugettext

        generic_error_message = _(
            "We're sorry, there was an error with processing your request. "
            "Please try reloading your page and trying again."
        )

        not_found_error_message = _(
            "The state of this problem has changed since you loaded this page. "
            "Please refresh your page."
        )

        if dispatch not in handlers:
            return 'Error: {} is not a known capa action'.format(dispatch)

        before = self.get_progress()
        before_attempts = self.attempts

        try:
            result = handlers[dispatch](data)

        except NotFoundError:
            log.info(
                "Unable to find data when dispatching %s to %s for user %s",
                dispatch,
                self.scope_ids.usage_id,
                self.scope_ids.user_id
            )
            _, _, traceback_obj = sys.exc_info()  # pylint: disable=redefined-outer-name
            raise ProcessingError(not_found_error_message), None, traceback_obj

        except Exception:
            log.exception(
                "Unknown error when dispatching %s to %s for user %s",
                dispatch,
                self.scope_ids.usage_id,
                self.scope_ids.user_id
            )
            _, _, traceback_obj = sys.exc_info()  # pylint: disable=redefined-outer-name
            raise ProcessingError(generic_error_message), None, traceback_obj

        after = self.get_progress()
        after_attempts = self.attempts
        progress_changed = (after != before) or (after_attempts != before_attempts)
        curr_score, total_possible = self.get_display_progress()

        result.update({
            'progress_changed': progress_changed,
            'current_score': curr_score,
            'total_possible': total_possible,
            'attempts_used': after_attempts,
        })

        return json.dumps(result, cls=ComplexEncoder)

    @property
    def display_name_with_default(self):
        """
        Constructs the display name for a CAPA problem.

        Default to the display_name if it isn't None or not an empty string,
        else fall back to problem category.
        """
        if self.display_name is None or not self.display_name.strip():
            return self.location.block_type

        return self.display_name


class CapaDescriptor(CapaFields, RawDescriptor):
    """
    Module implementing problems in the LON-CAPA format,
    as implemented by capa.capa_problem
    """
    INDEX_CONTENT_TYPE = 'CAPA'

    module_class = CapaModule
    resources_dir = None

    has_score = True
    show_in_read_only_mode = True
    template_dir_name = 'problem'
    mako_template = "widgets/problem-edit.html"
    js = {'js': [resource_string(__name__, 'js/src/problem/edit.js')]}
    js_module_name = "MarkdownEditingDescriptor"
    has_author_view = True
    css = {
        'scss': [
            resource_string(__name__, 'css/editor/edit.scss'),
            resource_string(__name__, 'css/problem/edit.scss')
        ]
    }

    # The capa format specifies that what we call max_attempts in the code
    # is the attribute `attempts`. This will do that conversion
    metadata_translations = dict(RawDescriptor.metadata_translations)
    metadata_translations['attempts'] = 'max_attempts'

    @classmethod
    def filter_templates(cls, template, course):
        """
        Filter template that contains 'latex' from templates.

        Show them only if use_latex_compiler is set to True in
        course settings.
        """
        return 'latex' not in template['template_id'] or course.use_latex_compiler

    def get_context(self):
        _context = RawDescriptor.get_context(self)
        _context.update({
            'markdown': self.markdown,
            'enable_markdown': self.markdown is not None,
            'enable_latex_compiler': self.use_latex_compiler,
        })
        return _context

    # VS[compat]
    # TODO (cpennington): Delete this method once all fall 2012 course are being
    # edited in the cms
    @classmethod
    def backcompat_paths(cls, path):
        return [
            'problems/' + path[8:],
            path[8:],
        ]

    @property
    def non_editable_metadata_fields(self):
        non_editable_fields = super(CapaDescriptor, self).non_editable_metadata_fields
        non_editable_fields.extend([
            CapaDescriptor.due,
            CapaDescriptor.graceperiod,
            CapaDescriptor.force_save_button,
            CapaDescriptor.markdown,
            CapaDescriptor.use_latex_compiler,
            CapaDescriptor.show_correctness,
        ])
        return non_editable_fields

    @property
    def problem_types(self):
        """ Low-level problem type introspection for content libraries filtering by problem type """
        try:
            tree = etree.XML(self.data)
        except etree.XMLSyntaxError:
            log.error('Error parsing problem types from xml for capa module {}'.format(self.display_name))
            return None  # short-term fix to prevent errors (TNL-5057). Will be more properly addressed in TNL-4525.
        registered_tags = responsetypes.registry.registered_tags()
        return {node.tag for node in tree.iter() if node.tag in registered_tags}

    def index_dictionary(self):
        """
        Return dictionary prepared with module content and type for indexing.
        """
        xblock_body = super(CapaDescriptor, self).index_dictionary()
        # Removing solutions and hints, as well as script and style
        capa_content = re.sub(
            re.compile(
                r"""
                    <solution>.*?</solution> |
                    <script>.*?</script> |
                    <style>.*?</style> |
                    <[a-z]*hint.*?>.*?</[a-z]*hint>
                """,
                re.DOTALL |
                re.VERBOSE),
            "",
            self.data
        )
        capa_content = escape_html_characters(capa_content)
        capa_body = {
            "capa_content": capa_content,
            "display_name": self.display_name,
        }
        if "content" in xblock_body:
            xblock_body["content"].update(capa_body)
        else:
            xblock_body["content"] = capa_body
        xblock_body["content_type"] = self.INDEX_CONTENT_TYPE
        xblock_body["problem_types"] = list(self.problem_types)
        return xblock_body

    def has_support(self, view, functionality):
        """
        Override the XBlock.has_support method to return appropriate
        value for the multi-device functionality.
        Returns whether the given view has support for the given functionality.
        """
        if functionality == "multi_device":
            types = self.problem_types  # Avoid calculating this property twice
            return types is not None and all(
                responsetypes.registry.get_class_for_tag(tag).multi_device_support
                for tag in types
            )
        return False

    def max_score(self):
        """
        Return the problem's max score
        """
        from capa.capa_problem import LoncapaProblem, LoncapaSystem
        capa_system = LoncapaSystem(
            ajax_url=None,
            anonymous_student_id=None,
            cache=None,
            can_execute_unsafe_code=None,
            get_python_lib_zip=None,
            DEBUG=None,
            filestore=self.runtime.resources_fs,
            i18n=self.runtime.service(self, "i18n"),
            node_path=None,
            render_template=None,
            seed=None,
            STATIC_URL=None,
            xqueue=None,
            matlab_api_key=None,
        )
        lcp = LoncapaProblem(
            problem_text=self.data,
            id=self.location.html_id(),
            capa_system=capa_system,
            capa_module=self,
            state={},
            seed=1,
            minimal_init=True,
        )
        return lcp.get_max_score()

    def generate_report_data(self, user_state_iterator, limit_responses=None):
        """
        Return a list of student responses to this block in a readable way.

        Arguments:
            user_state_iterator: iterator over UserStateClient objects.
                E.g. the result of user_state_client.iter_all_for_block(block_key)

            limit_responses (int|None): maximum number of responses to include.
                Set to None (default) to include all.

        Returns:
            each call returns a tuple like:
            ("username", {
                           "Question": "2 + 2 equals how many?",
                           "Answer": "Four",
                           "Answer ID": "98e6a8e915904d5389821a94e48babcf_10_1"
            })
        """

        from capa.capa_problem import LoncapaProblem, LoncapaSystem

        if self.category != 'problem':
            raise NotImplementedError()

        if limit_responses == 0:
            # Don't even start collecting answers
            return
        capa_system = LoncapaSystem(
            ajax_url=None,
            # TODO set anonymous_student_id to the anonymous ID of the user which answered each problem
            # Anonymous ID is required for Matlab, CodeResponse, and some custom problems that include
            # '$anonymous_student_id' in their XML.
            # For the purposes of this report, we don't need to support those use cases.
            anonymous_student_id=None,
            cache=None,
            can_execute_unsafe_code=lambda: None,
            get_python_lib_zip=(lambda: get_python_lib_zip(contentstore, self.runtime.course_id)),
            DEBUG=None,
            filestore=self.runtime.resources_fs,
            i18n=self.runtime.service(self, "i18n"),
            node_path=None,
            render_template=None,
            seed=1,
            STATIC_URL=None,
            xqueue=None,
            matlab_api_key=None,
        )
        _ = capa_system.i18n.ugettext

        count = 0
        for user_state in user_state_iterator:

            if 'student_answers' not in user_state.state:
                continue

            lcp = LoncapaProblem(
                problem_text=self.data,
                id=self.location.html_id(),
                capa_system=capa_system,
                # We choose to run without a fully initialized CapaModule
                capa_module=None,
                state={
                    'done': user_state.state.get('done'),
                    'correct_map': user_state.state.get('correct_map'),
                    'student_answers': user_state.state.get('student_answers'),
                    'has_saved_answers': user_state.state.get('has_saved_answers'),
                    'input_state': user_state.state.get('input_state'),
                    'seed': user_state.state.get('seed'),
                },
                seed=user_state.state.get('seed'),
                # extract_tree=False allows us to work without a fully initialized CapaModule
                # We'll still be able to find particular data in the XML when we need it
                extract_tree=False,
            )

            for answer_id, orig_answers in lcp.student_answers.items():
                # Some types of problems have data in lcp.student_answers that isn't in lcp.problem_data.
                # E.g. formulae do this to store the MathML version of the answer.
                # We exclude these rows from the report because we only need the text-only answer.
                if answer_id.endswith('_dynamath'):
                    continue

                if limit_responses and count >= limit_responses:
                    # End the iterator here
                    return

                question_text = lcp.find_question_label(answer_id)
                answer_text = lcp.find_answer_text(answer_id, current_answer=orig_answers)
                correct_answer_text = lcp.find_correct_answer_text(answer_id)

                count += 1
                report = {
                    _("Answer ID"): answer_id,
                    _("Question"): question_text,
                    _("Answer"): answer_text,
                }
                if correct_answer_text is not None:
                    report[_("Correct Answer")] = correct_answer_text
                yield (user_state.username, report)

    # Proxy to CapaModule for access to any of its attributes
    answer_available = module_attr('answer_available')
    submit_button_name = module_attr('submit_button_name')
    submit_button_submitting_name = module_attr('submit_button_submitting_name')
    submit_problem = module_attr('submit_problem')
    choose_new_seed = module_attr('choose_new_seed')
    closed = module_attr('closed')
    get_answer = module_attr('get_answer')
    get_problem = module_attr('get_problem')
    get_problem_html = module_attr('get_problem_html')
    get_state_for_lcp = module_attr('get_state_for_lcp')
    handle_input_ajax = module_attr('handle_input_ajax')
    hint_button = module_attr('hint_button')
    handle_problem_html_error = module_attr('handle_problem_html_error')
    handle_ungraded_response = module_attr('handle_ungraded_response')
    has_submitted_answer = module_attr('has_submitted_answer')
    is_attempted = module_attr('is_attempted')
    is_correct = module_attr('is_correct')
    is_past_due = module_attr('is_past_due')
    is_submitted = module_attr('is_submitted')
    lcp = module_attr('lcp')
    make_dict_of_responses = module_attr('make_dict_of_responses')
    new_lcp = module_attr('new_lcp')
    publish_grade = module_attr('publish_grade')
    rescore = module_attr('rescore')
    reset_problem = module_attr('reset_problem')
    save_problem = module_attr('save_problem')
    set_score = module_attr('set_score')
    set_state_from_lcp = module_attr('set_state_from_lcp')
    should_show_submit_button = module_attr('should_show_submit_button')
    should_show_reset_button = module_attr('should_show_reset_button')
    should_show_save_button = module_attr('should_show_save_button')
    update_score = module_attr('update_score')
