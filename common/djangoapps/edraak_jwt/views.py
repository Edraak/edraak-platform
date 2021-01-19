from importlib import import_module
import datetime
import logging

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
import jwt
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

log = logging.getLogger(__name__)


class EdraakAccessTokenView(APIView):
    @staticmethod
    def _failed_return(error_message, payload=None):
        if payload:
            msg = 'Request Access Token: {error_message}. Payload: {payload}'.format(
                error_message=error_message,
                payload=payload
            )
        else:
            msg = 'Request Access Token: {error_message}'.format(
                error_message=error_message,
            )

        if settings.DEBUG:
            print(msg)
        log.error(msg)

        return Response(
            status=status.HTTP_400_BAD_REQUEST,
            data={
                'message': error_message,
            }
        )

    @staticmethod
    def _check_seesion(session_key):
        engine = import_module(settings.SESSION_ENGINE)
        session = engine.SessionStore(session_key=session_key)
        return session.session_key and session.exists(session_key)

    def post(self, request):
        request_access_token = request.POST.get('request_access_token', None)
        if request_access_token is None:
            return self._failed_return('Missing request_access_token token')

        try:
            edraak_refresh_token = jwt.decode(
                request_access_token,
                settings.EDRAAK_JWT_SETTINGS['SECRET_KEY'],
                True,
                options={'verify_exp': True},
                algorithms=['HS256']
            )
            edraak_refresh_token = edraak_refresh_token['refresh_token']

            decoded_refresh_token = jwt.decode(
                edraak_refresh_token,
                settings.EDRAAK_JWT_SETTINGS['SECRET_KEY'],
                True,
                options={'verify_exp': True},
                algorithms=['HS256']
            )

        except jwt.exceptions.ExpiredSignatureError:
            return self._failed_return('Expired Refresh-token used')

        except:  # pylint: disable=broad-except
            print()
            raise ValueError('Bad Refresh-token')

        if decoded_refresh_token['type'] != 'refresh':
            return self._failed_return('Bad type for request_access_token', payload=decoded_refresh_token)
        elif not self._check_seesion(session_key=decoded_refresh_token['session_key']):
            if hasattr(request, 'user') and request.user and request.user.is_authenticated:
                logout(request=request)
                return self._failed_return(
                    'Logging out because of an old Refresh-token',
                    payload=decoded_refresh_token,
                )
            else:
                return self._failed_return(
                    'Old Refresh-token used',
                    payload=decoded_refresh_token,
                )

        decoded_refresh_token[u'exp'] = datetime.datetime.utcnow() + datetime.timedelta(
            seconds=settings.EDRAAK_JWT_SETTINGS['EXPIRATION_SECONDS']
        )
        decoded_refresh_token[u'type'] = 'access'
        decoded_refresh_token = jwt.encode(
            decoded_refresh_token,
            settings.EDRAAK_JWT_SETTINGS['SECRET_KEY'],
            'HS256'
        ).decode('utf-8')

        response = JsonResponse({
            'token': decoded_refresh_token
        })
        return response
