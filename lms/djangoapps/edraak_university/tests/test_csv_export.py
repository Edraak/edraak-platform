"""
Tests for the CSV Grade Report export to ensure correct University ID exports.

Also checks if the export can be disabled.
"""
from django.conf import settings
from django.contrib.auth.models import User

from mock import Mock, patch
import ddt

from xmodule.modulestore.tests.factories import CourseFactory
from instructor_task.tasks_helper import upload_grades_csv
from instructor_task.tests.test_tasks_helper import InstructorGradeReportTestCase
from student.models import UserProfile

from edraak_university.models import UniversityID
from edraak_university.helpers import is_csv_export_enabled_on_course


@ddt.ddt
class TestInstructorGradeReport(InstructorGradeReportTestCase):
    """
    Tests that CSV grade report generation works.
    """
    EMAIL_WITH_ID = 'john@example.org'
    EMAIL_WITHOUT_ID = 'doe@example.com'

    UNIVERSITY_ID_COLUMNS = ['Full Name', 'University ID']

    def setUp(self):
        super(TestInstructorGradeReport, self).setUp()
        # Avoid test duplication and only test using the export feature flag `EDRAAK_UNIVERSITY_CSV_EXPORT`.
        self.course = CourseFactory.create(enable_university_id=True)

    def create_student(self, username, email=None, mode='honor'):
        """
        Overrides the `create_student` parent class to create UniversityID for some students.
        """
        student = super(TestInstructorGradeReport, self).create_student(username, email, mode)

        if email == self.EMAIL_WITH_ID:
            UniversityID.objects.create(
                user=student,
                course_key=unicode(self.course.id),
                university_id='2011A-500',
            )

    def create_rows(self):
        """
        Creates CSV rows for the provided emails.
        """
        result_store = Mock(rows=[])
        current_task = Mock(update_state=Mock())

        def csv_rows_interceptor(rows, *_args, **_kwargs):
            """
            Mock the upload_csv_to_report_store to return the csv rows.
            """
            result_store.rows = rows

        self.create_student('student1', self.EMAIL_WITH_ID)
        self.create_student('student2', self.EMAIL_WITHOUT_ID)

        with patch('instructor_task.tasks_helper.upload_csv_to_report_store', side_effect=csv_rows_interceptor):
            with patch('instructor_task.tasks_helper._get_current_task') as mock_current_task:
                mock_current_task.return_value = current_task
                upload_grades_csv(None, None, self.course.id, None, 'graded')

        return result_store.rows

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_CSV_EXPORT': False})
    @ddt.data(*UNIVERSITY_ID_COLUMNS)
    def test_headers_disabled(self, header):
        rows = self.create_rows()

        self.assertIn('Email', rows[0])  # Sanity check for the header row
        self.assertIn('Username', rows[0])  # Sanity check
        self.assertFalse(is_csv_export_enabled_on_course(self.course))  # Sanity check

        self.assertEquals(len(rows[0]), len(rows[1]),
                          'The headers and data should have the same number of columns')

        self.assertNotIn(header, rows[0])  # Should not have the University ID headers if the feature is disabled

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_CSV_EXPORT': True})
    @ddt.data(*UNIVERSITY_ID_COLUMNS)
    def test_headers_enabled(self, header):
        rows = self.create_rows()

        self.assertIn('Email', rows[0])  # Sanity check
        self.assertIn('Username', rows[0])  # Sanity check
        self.assertTrue(is_csv_export_enabled_on_course(self.course))  # Sanity check

        self.assertEquals(len(rows[0]), len(rows[1]),
                          'The headers and data should have the same number of columns')

        self.assertIn(header, rows[0])  # Should have the University ID headers when the feature is enabled

    def get_row_as_dict(self, rows, index):
        """
        Allow accessing the row using the header name instead of integer index.

         e.g. `row['Full Name']` instead of `row[10]`
        """
        header_row = rows[0]
        data_row = rows[index]

        return dict(zip(header_row, data_row))

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_CSV_EXPORT': True})
    def test_with_university_id(self):
        rows = self.create_rows()
        row = self.get_row_as_dict(rows, index=1)

        user = User.objects.get(email=self.EMAIL_WITH_ID)
        id_object = UniversityID.objects.get(user=user)

        university_id_data = {
            'Full Name': id_object.get_full_name(),
            'University ID': id_object.university_id,
        }

        self.assertIn(user.email, row.values())  # Should contain the email, just a sanity check
        self.assertTrue(all(university_id_data), 'All data should be printed in the row')
        self.assertNotIn('N/A', university_id_data.values())
        self.assertDictContainsSubset(university_id_data, row)

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_CSV_EXPORT': True})
    def test_without_university_id(self):
        rows = self.create_rows()
        row = self.get_row_as_dict(rows, index=2)

        user = User.objects.get(email=self.EMAIL_WITHOUT_ID)
        user_profile = UserProfile.objects.get(user=user)

        with self.assertRaises(UniversityID.DoesNotExist):
            # Sanity check!
            UniversityID.objects.get(user=user)

        university_id_data = {column: 'N/A' for column in self.UNIVERSITY_ID_COLUMNS}
        university_id_data['Full Name'] = user_profile.name

        # The feature is enabled but there's no university ID data, all university ID CSV cells should contain 'N/A'
        self.assertDictContainsSubset(university_id_data, row)
