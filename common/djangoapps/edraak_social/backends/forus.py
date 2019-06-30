from social_core.backends.oauth import BaseOAuth2


class ForUsOAuth2(BaseOAuth2):

    name = 'forus'
    AUTHORIZATION_URL = 'https://www.forus.jo/oauth/authorize'
    ACCESS_TOKEN_URL = 'https://www.forus.jo/oauth/token'
    ACCESS_TOKEN_METHOD = 'POST'
    REFRESH_TOKEN_URL = 'https://www.forus.jo/oauth/token'
    USER_DATA_URL = 'https://www.forus.jo/oauth/userInfo'
    ID_KEY = 'uid'
    REDIRECT_STATE = False
    STATE_PARAMETER = False

    def get_user_details(self, response):
        fullname = response.get('first_name', '')
        last_name = response.get('last_name', '')
        if last_name:
            fullname = fullname + ' ' + last_name
        return {
            'username': response.get('username', response.get('name')),
            'email': response.get('email', ''),
            'fullname': fullname,
            'first_name': response.get('first_name', ''),
            'last_name': last_name,
            'gender': response.get('gender', 'o')
        }

    def user_data(self, access_token, *args, **kwargs):
        headers = {
            'Authorization': 'Bearer {}'.format(access_token)
        }
        return self.get_json(self.USER_DATA_URL, headers=headers)

    def get_redirect_uri(self, state=None):
        redirect_uri = super(ForUsOAuth2, self).get_redirect_uri(state)
        next_param = self.data.get('next')
        if next_param:
            redirect_uri += ('&' if '?' in redirect_uri else '?') + \
                   '{0}={1}'.format(
                       'next',
                       next_param.replace(' ', '+')
                   )
        return redirect_uri
