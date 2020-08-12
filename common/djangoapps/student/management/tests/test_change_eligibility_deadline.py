""" Test the change_eligibility_deadline command line script."""

from datetime import datetime, timedelta

from course_modes.tests.factories import CourseMode
from django.core.management import call_command
from opaque_keys import InvalidKeyError
from six import text_type
from student.models import CourseEnrollment, User
from student.tests.factories import UserFactory
from testfixtures import LogCapture
from xmodule.modulestore.tests.django_utils import SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory

from openedx.core.djangoapps.credit.models import CreditCourse, CreditEligibility

LOGGER_NAME = 'student.management.commands.change_eligibility_deadline'
command_args = '--username {username} --course {course} --date {date}'


class ChangeEligibilityDeadlineTests(SharedModuleStoreTestCase):
    """ Test the deadline change functionality of the change_eligibility_deadline script."""

    def setUp(self):
        """ Initial set up for tests """
        super(ChangeEligibilityDeadlineTests, self).setUp()
        self.course = CourseFactory.create()

        self.enrolled_user = UserFactory.create(username='amy', email='amy@pond.com', password='password')
        CourseEnrollment.enroll(self.enrolled_user, self.course.id, mode=CourseMode.CREDIT_MODE).save()

        credit_course = CreditCourse.objects.create(course_key=self.course.id)
        self.credit_eligibility = CreditEligibility.objects.create(
            username=self.enrolled_user.username,
            course=credit_course,
        )
        self.credit_eligibility.deadline = datetime.strptime('2013-12-30', '%Y-%m-%d')
        self.credit_eligibility.save()

    def test_invalid_command_arguments(self):
        """ Test command with invalid arguments """
        course_id_str = text_type(self.course.id)
        username = self.enrolled_user.username

        # Incorrect username
        with self.assertRaises(User.DoesNotExist):
            call_command('change_eligibility_deadline',
                         *command_args.format(username='XYZ', course=course_id_str, date='2018-12-30').split(' ')
                         )
        # Incorrect course id
        with self.assertRaises(InvalidKeyError):
            call_command('change_eligibility_deadline',
                         *command_args.format(username=username, course='XYZ', date='2018-12-30').split(' ')
                         )
        # Student not enrolled
        with self.assertRaises(CourseEnrollment.DoesNotExist):
            unenrolled_user = UserFactory.create()
            call_command('change_eligibility_deadline',
                         *command_args.format(username=unenrolled_user.username, course=course_id_str,
                                              date='2018-12-30').split(' ')
                         )
        # Date format Invalid
        with self.assertRaises(ValueError):
            call_command('change_eligibility_deadline',
                         *command_args.format(username=username, course=course_id_str, date='30-12-2018').split(' ')
                         )
        # Date not provided
        with self.assertRaises(KeyError):
            call_command('change_eligibility_deadline',
                         *command_args.format(username=username, course=course_id_str,).split(' '))

    def test_invalid_date(self):
        """
        Tests the command when the date is prior to today

        In case the date given as deadline is prior to today it sets the deadline to
        default value which is one month from today. It then continues to run the code
        to change eligibility deadline.
        """
        course_key = text_type(self.course.id)
        username = self.enrolled_user.username

        # Test Date set prior to today
        with LogCapture(LOGGER_NAME) as logger:
            call_command(
                'change_eligibility_deadline',
                *command_args.format(username=username, course=course_key, date='2000-12-30').split(' ')
            )
            logger.check(
                (LOGGER_NAME, 'WARNING', 'Invalid date or date not provided. Setting deadline to one month from now'),
                (LOGGER_NAME, 'INFO', 'Successfully updated credit eligibility deadline for {}'.format(username))
            )

    def test_valid_command_arguments(self):
        """ Test command with valid arguments """
        course_key = text_type(self.course.id)
        username = self.enrolled_user.username
        new_deadline = datetime.utcnow() + timedelta(days=30)

        call_command('change_eligibility_deadline',
                     *command_args.format(username=username, course=course_key, date=new_deadline.date()).split(' ')
                     )

        credit_eligibility = CreditEligibility.objects.get(username=username,
                                                           course__course_key=self.course.id)
        credit_deadline = credit_eligibility.deadline.date()
        self.assertEqual(credit_deadline, new_deadline.date())
