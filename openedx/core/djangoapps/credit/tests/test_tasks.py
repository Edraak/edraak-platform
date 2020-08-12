"""
Tests for credit course tasks.
"""

import mock
from datetime import datetime

from openedx.core.djangoapps.credit.api import get_credit_requirements
from openedx.core.djangoapps.credit.exceptions import InvalidCreditRequirements
from openedx.core.djangoapps.credit.models import CreditCourse
from openedx.core.djangoapps.credit.signals import on_course_publish
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory

from edx_proctoring.api import create_exam


class TestTaskExecution(ModuleStoreTestCase):
    """Set of tests to ensure that the task code will do the right thing when
    executed directly.

    The test course gets created without the listeners being present, which
    allows us to ensure that when the listener is executed, it is done as
    expected.
    """
    shard = 2

    def mocked_set_credit_requirements(course_key, requirements):  # pylint: disable=no-self-argument, unused-argument
        """Used as a side effect when mocking method credit api method
        'set_credit_requirements'.
        """
        raise InvalidCreditRequirements

    def setUp(self):
        super(TestTaskExecution, self).setUp()

        self.course = CourseFactory.create(start=datetime(2015, 3, 1))
        self.section = ItemFactory.create(parent=self.course, category='chapter', display_name='Test Section')
        self.subsection = ItemFactory.create(parent=self.section, category='sequential', display_name='Test Subsection')
        self.vertical = ItemFactory.create(parent=self.subsection, category='vertical', display_name='Test Unit')

    def test_task_adding_requirements_invalid_course(self):
        """
        Test that credit requirements cannot be added for non credit course.
        """
        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)
        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)

    def test_task_adding_requirements(self):
        """Test that credit requirements are added properly for credit course.

        Make sure that the receiver correctly fires off the task when
        invoked by signal.
        """
        self.add_credit_course(self.course.id)
        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)
        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 1)

    def test_proctored_exam_requirements(self):
        """
        Make sure that proctored exams are being registered as requirements
        """

        self.add_credit_course(self.course.id)

        create_exam(
            course_id=unicode(self.course.id),
            content_id=unicode(self.subsection.location),
            exam_name='A Proctored Exam',
            time_limit_mins=10,
            is_proctored=True,
            is_active=True
        )

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)

        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 2)
        self.assertEqual(requirements[1]['namespace'], 'proctored_exam')
        self.assertEqual(requirements[1]['name'], unicode(self.subsection.location))
        self.assertEqual(requirements[1]['display_name'], 'A Proctored Exam')
        self.assertEqual(requirements[1]['criteria'], {})

    def test_proctored_exam_filtering(self):
        """
        Make sure that timed or inactive exams do not end up in the requirements table
        Also practice protored exams are not a requirement
        """

        self.add_credit_course(self.course.id)
        create_exam(
            course_id=unicode(self.course.id),
            content_id='foo',
            exam_name='A Proctored Exam',
            time_limit_mins=10,
            is_proctored=False,
            is_active=True
        )

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)

        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 1)

        # make sure we don't have a proctoring requirement
        self.assertFalse([
            requirement
            for requirement in requirements
            if requirement['namespace'] == 'proctored_exam'
        ])

        create_exam(
            course_id=unicode(self.course.id),
            content_id='foo2',
            exam_name='A Proctored Exam',
            time_limit_mins=10,
            is_proctored=True,
            is_active=False
        )

        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 1)

        # make sure we don't have a proctoring requirement
        self.assertFalse([
            requirement
            for requirement in requirements
            if requirement['namespace'] == 'proctored_exam'
        ])

        # practice proctored exams aren't requirements
        create_exam(
            course_id=unicode(self.course.id),
            content_id='foo3',
            exam_name='A Proctored Exam',
            time_limit_mins=10,
            is_proctored=True,
            is_active=True,
            is_practice_exam=True
        )

        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 1)

        # make sure we don't have a proctoring requirement
        self.assertFalse([
            requirement
            for requirement in requirements
            if requirement['namespace'] == 'proctored_exam'
        ])

    @mock.patch(
        'openedx.core.djangoapps.credit.tasks.set_credit_requirements',
        mock.Mock(
            side_effect=mocked_set_credit_requirements
        )
    )
    def test_retry(self):
        """Test that adding credit requirements is retried when
        'InvalidCreditRequirements' exception is raised.

        Make sure that the receiver correctly fires off the task when
        invoked by signal
        """
        self.add_credit_course(self.course.id)
        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)
        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)

    def test_credit_requirement_blocks_ordering(self):
        """
        Test ordering of proctoring blocks.
        """

        self.add_credit_course(self.course.id)
        subsection = ItemFactory.create(parent=self.section, category='sequential', display_name='Dummy Subsection')
        create_exam(
            course_id=unicode(self.course.id),
            content_id=unicode(subsection.location),
            exam_name='A Proctored Exam',
            time_limit_mins=10,
            is_proctored=True,
            is_active=True
        )

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 0)
        on_course_publish(self.course.id)

        requirements = get_credit_requirements(self.course.id)
        self.assertEqual(len(requirements), 2)
        self.assertEqual(requirements[1]['namespace'], 'proctored_exam')
        self.assertEqual(requirements[1]['name'], unicode(subsection.location))
        self.assertEqual(requirements[1]['display_name'], 'A Proctored Exam')
        self.assertEqual(requirements[1]['criteria'], {})

        # Primary sort is based on start date
        on_course_publish(self.course.id)
        requirements = get_credit_requirements(self.course.id)
        # grade requirement is added on publish of the requirements
        self.assertEqual(len(requirements), 2)
        # check requirements are added in the desired order
        # 1st Minimum grade then the blocks with start date than other blocks
        self.assertEqual(requirements[0]["display_name"], "Minimum Grade")
        self.assertEqual(requirements[1]["display_name"], "A Proctored Exam")

    def add_credit_course(self, course_key):
        """Add the course as a credit.

        Args:
            course_key(CourseKey): Identifier for the course

        Returns:
            CreditCourse object added
        """
        credit_course = CreditCourse(course_key=course_key, enabled=True)
        credit_course.save()
        return credit_course
