from social_core.pipeline.social_auth import associate_by_email
from social_core.pipeline.user import create_user

from student.models import UserProfile

from .utils import forus_authentication_only


@forus_authentication_only
def save_redirect_param(strategy, *args, **kwargs):
    strategy.request.session['next'] = \
        strategy.request.GET.get('next', '').replace(' ', '+')


@forus_authentication_only
def associate_account_by_email(backend, details, user, *args, **kwargs):
    """
    This pipeline step associates the current social auth with the user which has the
    same email address in the database.  It defers from social library's associate_by_email
    implementation, which verifies that only a single database user is associated with the email.
    """
    return associate_by_email(backend, details, user, *args, **kwargs)


@forus_authentication_only
def create_user_account(strategy, details, backend, user=None, *args, **kwargs):

    if not user:
        res = create_user(
            strategy=strategy,
            details=details,
            backend=backend,
            user=user,
            *args,
            **kwargs
        )
        res['is_new_forus_user'] = res['is_new']
        return res


@forus_authentication_only
def is_new_user(is_new_forus_user=False, *args, **kwargs):
    if is_new_forus_user:
        return {'is_new': True}


@forus_authentication_only
def get_account_details(user, *args, **kwargs):
    details = kwargs.get('details', {})
    name = u"{} {}".format(details.get('first_name', ''),
                           details.get('last_name','')).strip()
    return {
        'profile_details': {
            'name': name,
            'gender': 'm' if details.get('gender') == 'male' else 'f'
        }
    }


@forus_authentication_only
def create_student_profile(user, *args, **kwargs):
    try:
        user.profile
    except UserProfile.DoesNotExist:
        profile_details = kwargs.get('profile_details', {})
        profile_details['user_id'] = user.id
        UserProfile.objects.create(**profile_details)
