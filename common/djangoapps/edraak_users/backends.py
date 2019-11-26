from django.contrib.auth.models import User
from django.contrib.auth.backends import ModelBackend

from student.constants import CHILD_OF_USER_PERMISSION_GROUP_PREFIX


class EdraakChildAuthenticationBackend(ModelBackend):

    def authenticate(self, **kwargs):
        request = kwargs.get("request")
        if request and hasattr(request, 'user') and request.user.is_authenticated():
            username = kwargs.get("username")
            child_group_name = CHILD_OF_USER_PERMISSION_GROUP_PREFIX.format(request.user.username)
            try:
                return User.objects.filter(groups__name=child_group_name).get(username=username)
            except User.DoesNotExist:
                return None
        return None
