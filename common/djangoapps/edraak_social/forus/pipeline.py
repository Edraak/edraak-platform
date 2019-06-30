from social_core.pipeline.social_auth import associate_by_email


FORUS_BACKEND_NAME = 'forus'

def associate_forus_account_by_email(backend, details, user,
                                     backend_name, *args, **kwargs):
    """
    This pipeline step associates the current social auth with the user with the
    same email address in the database.  It defers to the social library's associate_by_email
    implementation, which verifies that only a single database user is associated with the email.
    """
    if backend_name == FORUS_BACKEND_NAME:
        return associate_by_email(backend, details, user, *args, **kwargs)


def get_forus_accont_details(user, backend_name, *args, **kwargs):
    if backend_name == FORUS_BACKEND_NAME:
        details = kwargs.get('details', {})
        name = u"{} {}".format(details.get('first_name', ''),
                               details.get('last_name','')).strip()
        return {
            'profile_details': {
                'name': name,
                'gender': 'm' if details.get('gender') == 'male' else 'f'
            }
        }
