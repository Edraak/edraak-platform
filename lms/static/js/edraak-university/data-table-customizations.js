jQuery(function ($) {
    'use strict';

    /*
     * Localize the University ID data tables and change both sort and pagination options.
     */

    $('table.instructor-list').DataTable({
        lengthMenu: [
            // Customize the options in page length drop down menu.
            [50, 100, 200, -1],
            ['50', '100', '200', gettext('All')]
        ],
        'columnDefs': [
            // Customize the order options
            {'orderable': true, 'targets': 'sortable'},
            {'orderable': false, 'targets': '_all'}
        ],
        language: {
            'sProcessing': gettext('Processing...'),
            'sLengthMenu': gettext('Show _MENU_ entries'),
            'sZeroRecords': gettext('No records where found'),
            'sInfo': gettext('Showing _START_ to _END_ out of _TOTAL_ entries.'),
            'sInfoEmpty': gettext('No records to show.'),
            'sInfoFiltered': gettext('Filtered out of _MAX_ entries.'),
            'sInfoPostFix': '',
            'sSearch': gettext('Search:'),
            'sUrl': '',
            'oPaginate': {
                'sFirst': pgettext('pagination', 'First'),
                'sPrevious': pgettext('pagination', 'Previous'),
                'sNext': pgettext('pagination', 'Next'),
                'sLast': pgettext('pagination', 'Last')
            }
        }
    });
});
