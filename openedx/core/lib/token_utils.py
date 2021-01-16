"""Utilities for working with ID tokens."""
import json
from time import time

from Cryptodome.PublicKey import RSA
from django.conf import settings
from django.utils.functional import cached_property
from jwkest.jwk import KEYS, RSAKey
from jwkest.jws import JWS

from student.models import UserProfile, anonymous_id_for_user


class JwtBuilder(object):
    """Utility for building JWTs.

    Unifies diverse approaches to JWT creation in a single class. This utility defaults to using the system's
    JWT configuration.

    NOTE: This utility class will allow you to override the signing key and audience claim to support those
    clients which still require this. This approach to JWT creation is DEPRECATED. Avoid doing this for new clients.

    Arguments:
        user (User): User for which to generate the JWT.

    Keyword Arguments:
        asymmetric (Boolean): Whether the JWT should be signed with this app's private key.
        secret (string): Overrides configured JWT secret (signing) key. Unused if an asymmetric signature is requested.
        issuer (string): Overrides configured JWT issuer.
    """

    def __init__(self, user, asymmetric=False, secret=None, issuer=None):
        self.user = user
        self.asymmetric = asymmetric
        self.secret = secret
        self.issuer = issuer
        self.jwt_auth = settings.JWT_AUTH

    def build_token(self, scopes, expires_in=None, aud=None, additional_claims=None):
        """Returns a JWT access token.

        Arguments:
            scopes (list): Scopes controlling which optional claims are included in the token.

        Keyword Arguments:
            expires_in (int): Time to token expiry, specified in seconds.
            aud (string): Overrides configured JWT audience claim.
            additional_claims (dict): Additional claims to include in the token.

        Returns:
            str: Encoded JWT
        """
        now = int(time())
        expires_in = expires_in or self.jwt_auth['JWT_EXPIRATION']
        payload = {
            # TODO Consider getting rid of this claim since we don't use it.
            'aud': aud if aud else self.jwt_auth['JWT_AUDIENCE'],
            'exp': now + expires_in,
            'iat': now,
            'iss': self.issuer if self.issuer else self.jwt_auth['JWT_ISSUER'],
            'preferred_username': self.user.username,
            'scopes': scopes,
            'version': self.jwt_auth['JWT_SUPPORTED_VERSION'],
            'sub': anonymous_id_for_user(self.user, None),
        }
        print('.........payload = {}'.format(payload))
        if additional_claims:
            payload.update(additional_claims)

        for scope in scopes:
            handler = self.claim_handlers.get(scope)

            if handler:
                handler(payload)

        print('.........payload = {}'.format(payload))
        the_token = self.encode(payload)
        print('.........the_token = {}'.format(the_token))
        return the_token

    @cached_property
    def claim_handlers(self):
        """Returns a dictionary mapping scopes to methods that will add claims to the JWT payload."""

        return {
            'email': self.attach_email_claim,
            'profile': self.attach_profile_claim
        }

    def attach_email_claim(self, payload):
        """Add the email claim details to the JWT payload."""
        payload['email'] = self.user.email

    def attach_profile_claim(self, payload):
        """Add the profile claim details to the JWT payload."""
        try:
            # Some users (e.g., service users) may not have user profiles.
            name = UserProfile.objects.get(user=self.user).name
        except UserProfile.DoesNotExist:
            name = None

        payload.update({
            'name': name,
            'family_name': self.user.last_name,
            'given_name': self.user.first_name,
            'administrator': self.user.is_staff,
        })

    def encode(self, payload):
        """Encode the provided payload."""
        keys = KEYS()

        if self.asymmetric:
            keys.add(RSAKey(key=RSA.importKey(settings.JWT_PRIVATE_SIGNING_KEY)))
            algorithm = 'RS512'
        else:
            key = self.secret if self.secret else self.jwt_auth['JWT_SECRET_KEY']
            keys.add({'key': key, 'kty': 'oct'})
            algorithm = self.jwt_auth['JWT_ALGORITHM']
        print('.........key = {}'.format(key))
        print('.........keys = {}'.format(keys))
        print('.........algorithm = {}'.format(algorithm))
        data = json.dumps(payload)
        print('.........data = {}'.format(data))
        jws = JWS(data, alg=algorithm)
        print('.........jws = {}'.format(jws))
        return jws.sign_compact(keys=keys)
