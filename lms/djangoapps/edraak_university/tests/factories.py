"""
Dummy factories for tests
"""
from factory import SubFactory, Sequence
from factory.django import DjangoModelFactory
from student.tests.factories import UserFactory

from edraak_university.models import UniversityID


class UniversityIDFactory(DjangoModelFactory):
    """
    A factory to generate UniversityID objects for tests while avoiding code duplication in tests.
    """

    user = SubFactory(UserFactory)
    university_id = Sequence('2005-A-{0}'.format)
    section_number = Sequence(unicode)

    class Meta(object):
        model = UniversityID
