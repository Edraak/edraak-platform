# pylint: disable=missing-docstring
# pylint: disable=no-member
# pylint: disable=redefined-outer-name

# Lettuce formats proposed definitions for unimplemented steps with the
# argument name "step" instead of "_step" and pylint does not like that.
# pylint: disable=unused-argument

from lettuce import step, world
from openedx.core.lib.tests.tools import assert_equal, assert_in, assert_true  # pylint: disable=no-name-in-module

DISPLAY_NAME = "Display Name"


@step(u'I add this type of single step component:$')
def add_a_single_step_component(step):
    for step_hash in step.hashes:
        component = step_hash['Component']
        assert_in(component, ['Discussion', 'Video'])

        world.create_component_instance(
            step=step,
            category='{}'.format(component.lower()),
        )


@step(u'I see this type of single step component:$')
def see_a_single_step_component(step):
    for step_hash in step.hashes:
        component = step_hash['Component']
        assert_in(component, ['Discussion', 'Video'])
        component_css = '.xmodule_{}Module'.format(component)
        assert_true(world.is_css_present(component_css),
                    "{} couldn't be found".format(component))


@step(u'I add this type of( Advanced)? (HTML|Problem) component:$')
def add_a_multi_step_component(step, is_advanced, category):
    for step_hash in step.hashes:
        world.create_component_instance(
            step=step,
            category='{}'.format(category.lower()),
            component_type=step_hash['Component'],
            is_advanced=bool(is_advanced),
        )


@step(u'I see (HTML|Problem) components in this order:')
def see_a_multi_step_component(step, category):

    # Wait for all components to finish rendering
    if category == 'HTML':
        selector = 'li.studio-xblock-wrapper div.xblock-student_view'
    else:
        selector = 'li.studio-xblock-wrapper div.xblock-author_view'
    world.wait_for(lambda _: len(world.css_find(selector)) == len(step.hashes))

    for idx, step_hash in enumerate(step.hashes):
        if category == 'HTML':
            html_matcher = {
                'Text': '\n    \n',
                'Announcement': '<h3 class="hd hd-2">Announcement Date</h3>',
                'Zooming Image Tool': '<h3 class="hd hd-2">Zooming Image Tool</h3>',
                'E-text Written in LaTeX': '<h3 class="hd hd-2">Example: E-text page</h3>',
                'Raw HTML': '<p>This template is similar to the Text template. The only difference is',
            }
            actual_html = world.css_html(selector, index=idx)
            assert_in(html_matcher[step_hash['Component']].strip(), actual_html.strip())
        else:
            actual_text = world.css_text(selector, index=idx)
            assert_in(step_hash['Component'], actual_text)


@step(u'I see a "([^"]*)" Problem component$')
def see_a_problem_component(step, category):
    component_css = '.xmodule_CapaModule'
    assert_true(world.is_css_present(component_css),
                'No problem was added to the unit.')

    problem_css = '.studio-xblock-wrapper .xblock-student_view'
    # This view presents the given problem component in uppercase. Assert that the text matches
    # the component selected
    assert_true(world.css_contains_text(problem_css, category))


@step(u'I add a "([^"]*)" "([^"]*)" component$')
def add_component_category(step, component, category):
    assert category in ('single step', 'HTML', 'Problem', 'Advanced Problem')
    given_string = 'I add this type of {} component:'.format(category)
    step.given('{}\n{}\n{}'.format(given_string, '|Component|', '|{}|'.format(component)))


@step(u'I delete all components$')
def delete_all_components(step):
    count = len(world.css_find('.reorderable-container .studio-xblock-wrapper'))
    step.given('I delete "' + str(count) + '" component')


@step(u'I delete "([^"]*)" component$')
def delete_components(step, number):
    world.wait_for_xmodule()
    delete_btn_css = '.delete-button'
    prompt_css = '#prompt-warning'
    btn_css = '{} .action-primary'.format(prompt_css)
    saving_mini_css = '#page-notification .wrapper-notification-mini'
    for _ in range(int(number)):
        world.css_click(delete_btn_css)
        assert_true(
            world.is_css_present('{}.is-shown'.format(prompt_css)),
            msg='Waiting for the confirmation prompt to be shown')

        # Pressing the button via css was not working reliably for the last component
        # when run in Chrome.
        if world.browser.driver_name == 'Chrome':
            world.browser.execute_script("$('{}').click()".format(btn_css))
        else:
            world.css_click(btn_css)

        # Wait for the saving notification to pop up then disappear
        if world.is_css_present('{}.is-shown'.format(saving_mini_css)):
            world.css_find('{}.is-hiding'.format(saving_mini_css))


@step(u'I see no components')
def see_no_components(steps):
    assert world.is_css_not_present('li.studio-xblock-wrapper')


@step(u'I delete a component')
def delete_one_component(step):
    world.css_click('.delete-button')


@step(u'I edit and save a component')
def edit_and_save_component(step):
    world.css_click('.edit-button')
    world.css_click('.save-button')


@step(u'I duplicate the (first|second|third) component$')
def duplicated_component(step, ordinal):
    ord_map = {
        "first": 0,
        "second": 1,
        "third": 2,
    }
    index = ord_map[ordinal]
    duplicate_btn_css = '.duplicate-button'
    world.css_click(duplicate_btn_css, int(index))


@step(u'I see a Problem component with display name "([^"]*)" in position "([^"]*)"$')
def see_component_in_position(step, display_name, index):
    component_css = '.xmodule_CapaModule'

    def find_problem(_driver):
        return world.css_text(component_css, int(index)).startswith(display_name)

    world.wait_for(find_problem, timeout_msg='Did not find the duplicated problem')


@step(u'I see the display name is "([^"]*)"')
def check_component_display_name(step, display_name):
    # The display name for the unit uses the same structure, must differentiate by level-element.
    label = world.css_html(".level-element>header>div>div>span.xblock-display-name")
    assert_equal(display_name, label)


@step(u'I change the display name to "([^"]*)"')
def change_display_name(step, display_name):
    world.edit_component_and_select_settings()
    index = world.get_setting_entry_index(DISPLAY_NAME)
    world.set_field_value(index, display_name)
    world.save_component()


@step(u'I unset the display name')
def unset_display_name(step):
    world.edit_component_and_select_settings()
    world.revert_setting_entry(DISPLAY_NAME)
    world.save_component()
