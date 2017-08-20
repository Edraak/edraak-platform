"""
Dummy factories for tests
"""
import factory
from factory.django import DjangoModelFactory

from student.models import CourseEnrollment
from student.tests.factories import UserFactory

from edraak_university.models import UniversityID


class UniversityIDFactory(DjangoModelFactory):
    """
    A factory to generate UniversityID objects for tests while avoiding code duplication in tests.
    """

    user = factory.SubFactory(UserFactory)
    university_id = factory.Sequence('2005-A-{0}'.format)

    @factory.post_generation
    def course_enrollment(self, create, extracted, **kwargs):
        CourseEnrollment.get_or_create_enrollment(
            course_key=self.course_key,
            user=self.user,
        )

    class Meta(object):
        model = UniversityID
