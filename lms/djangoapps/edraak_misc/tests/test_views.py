"""
Tests for Edraak Misc.
"""
import ddt

from django.core.urlresolvers import reverse

from edraak_tests.tests.helpers import ModuleStoreLoggedInTestCase


@ddt.ddt
class AllTests(ModuleStoreLoggedInTestCase):
    def setUp(self):
        super(AllTests, self).setUp()

    @ddt.data('check_student_grades', 'course_complete_status')
    def test_login_required(self, view):
        self.client.logout()

        view_full_name = 'edraak_misc:{view}'.format(view=view)
        url = reverse(view_full_name, args=['edx/Demo/2019'])

        res = self.client.get(url)
        self.assertRedirects(res, '/login?next={}'.format(url))

    @ddt.data(
        ('check_student_grades', '"success": '),
        ('course_complete_status', '"complete": '),
    )
    @ddt.unpack
    def test_urls_validity(self, view, contains_string):
        view_full_name = 'edraak_misc:{view}'.format(view=view)

        url = reverse(view_full_name, args=[self.course.id])

        res = self.client.get(url)
        self.assertContains(res, contains_string, status_code=200)
