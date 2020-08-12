"""
Cohorts API serializers.
"""
from rest_framework import serializers

from django.contrib.auth.models import User


class CohortUsersAPISerializer(serializers.ModelSerializer):
    """
    Serializer for cohort users.
    """
    name = serializers.SerializerMethodField('get_full_name')

    def get_full_name(self, model):
        """Return the full name of the user."""
        return '{} {}'.format(model.first_name, model.last_name)

    class Meta:
        model = User
        fields = ('username', 'email', 'name')
