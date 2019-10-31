"""
Tests for the CSV Grade Report export to ensure correct University ID exports.

Also checks if the export can be disabled.
"""
from django.conf import settings
from django.contrib.auth.models import User

from mock import Mock, patch
import ddt

from xmodule.modulestore.tests.factories import CourseFactory
from lms.djangoapps.instructor_task.tasks_helper.grades import CourseGradeReport
from lms.djangoapps.instructor_task.tests.test_tasks_helper import InstructorGradeReportTestCase

from edraak_university.models import UniversityID
from edraak_university.helpers import is_csv_export_enabled_on_course


@ddt.ddt
class TestInstructorEdraakGradeReport(InstructorGradeReportTestCase):
    """
    Tests that CSV grade report generation works.
    """

    EMAIL_WITH_ID = 'john@example.org'
    EMAIL_WITHOUT_ID = 'doe@example.com'

    UNIVERSITY_ID_COLUMNS = ['Full Name', 'University ID']

    def setUp(self):
        super(TestInstructorEdraakGradeReport, self).setUp()
        # Avoid test duplication and only test using the export feature flag `EDRAAK_UNIVERSITY_CSV_EXPORT`.
        self.course = CourseFactory.create(enable_university_id=True)

    def create_student(self, username, email=None, mode='honor', enrollment_active=True):
        """
        Overrides the `create_student` parent class to create UniversityID for some students.
        """
        student = super(TestInstructorEdraakGradeReport, self).create_student(username, email, mode)

        if email == self.EMAIL_WITH_ID:
            UniversityID.objects.create(
                user=student,
                course_key=self.course.id,
                university_id='2011A-500',
            )

    def create_rows(self):
        self.create_student('student1', self.EMAIL_WITH_ID)
        self.create_student('student2', self.EMAIL_WITHOUT_ID)
        self.current_task = Mock()

        self.current_task.update_state = Mock()
        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task') as mock_current_task:
            mock_current_task.return_value = self.current_task
            CourseGradeReport.generate(None, None, self.course.id, None, 'graded')

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_CSV_EXPORT': False})
    @ddt.data(*UNIVERSITY_ID_COLUMNS)
    def test_headers_disabled(self, header):
        """
        Test that students with unicode characters in emails is handled.
        """
        assert not is_csv_export_enabled_on_course(self.course)  # Sanity check
        self.create_rows()
        headers = self.get_csv_row_with_headers()
        assert header not in headers

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_CSV_EXPORT': True})
    @ddt.data(*UNIVERSITY_ID_COLUMNS)
    def test_headers_enabled(self, header):
        """
        Test that students with unicode characters in emails is handled.
        """
        assert is_csv_export_enabled_on_course(self.course)  # Sanity check
        self.create_rows()
        headers = self.get_csv_row_with_headers()
        assert header in headers

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_CSV_EXPORT': True})
    def test_with_university_id(self):
        self.create_rows()

        user_with_id = User.objects.get(email=self.EMAIL_WITH_ID)
        id_object = UniversityID.objects.get(user=user_with_id)

        user_without_id = User.objects.get(email=self.EMAIL_WITHOUT_ID)
        with self.assertRaises(UniversityID.DoesNotExist):
            # Sanity check!
            UniversityID.objects.get(user=user_without_id)

        rows = [
            {
                'Username': user_with_id.username,
                'Email': user_with_id.email,
                'University ID': id_object.university_id,
                'Full Name': id_object.get_full_name(),
            },
            {
                'Username': user_without_id.username,
                'Email': user_without_id.email,
                'Full Name': user_without_id.profile.name,
                'University ID': 'N/A',
            },
         ]

        self.verify_rows_in_csv(rows, verify_order=True, ignore_other_columns=True)
