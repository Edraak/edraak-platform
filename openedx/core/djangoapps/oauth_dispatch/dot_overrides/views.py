"""
Classes that override default django-oauth-toolkit behavior
"""
from __future__ import unicode_literals

from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.http import HttpResponseUriRedirect
from oauth2_provider.models import get_access_token_model, get_application_model
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views import AuthorizationView

from openedx.core.djangoapps.oauth_dispatch.models import ApplicationOrganization


# TODO (ARCH-83) remove once we have full support of OAuth Scopes
class EdxOAuth2AuthorizationView(AuthorizationView):
    """
    Override the AuthorizationView's GET method so the user isn't
    prompted to approve the application if they have already in
    the past, even if their access token is expired.

    This is a temporary override of the base implementation
    in order to accommodate our Restricted Applications support
    until OAuth Scopes are fully supported.
    """
    def get(self, request, *args, **kwargs):
        # Note: This code is copied from https://github.com/evonove/django-oauth-toolkit/blob/34f3b7b3511c15686039079026165feaadb1b87d/oauth2_provider/views/base.py#L111
        # Places that we have changed are noted with ***.
        try:
            # *** Moved code to get the require_approval value earlier on so we can
            # circumvent our custom code in the case when auto_even_if_expired
            # isn't required.
            require_approval = request.GET.get(
                "approval_prompt",
                oauth2_settings.REQUEST_APPROVAL_PROMPT,
            )
            if require_approval != 'auto_even_if_expired':
                return super(EdxOAuth2AuthorizationView, self).get(request, *args, **kwargs)

            scopes, credentials = self.validate_authorization_request(request)
            all_scopes = get_scopes_backend().get_all_scopes()
            kwargs["scopes_descriptions"] = [all_scopes[scope] for scope in scopes]
            kwargs['scopes'] = scopes

            # at this point we know an Application instance with such client_id exists in the database
            application = get_application_model().objects.get(client_id=credentials['client_id'])
            content_orgs = ApplicationOrganization.get_related_org_names(
                application,
                relation_type=ApplicationOrganization.RELATION_TYPE_CONTENT_ORG
            )
            kwargs['application'] = application
            kwargs['content_orgs'] = content_orgs
            kwargs['client_id'] = credentials['client_id']
            kwargs['redirect_uri'] = credentials['redirect_uri']
            kwargs['response_type'] = credentials['response_type']
            kwargs['state'] = credentials['state']

            self.oauth2_data = kwargs
            # following two loc are here only because of https://code.djangoproject.com/ticket/17795
            form = self.get_form(self.get_form_class())
            kwargs['form'] = form

            # If skip_authorization field is True, skip the authorization screen even
            # if this is the first use of the application and there was no previous authorization.
            # This is useful for in-house applications-> assume an in-house applications
            # are already approved.
            if application.skip_authorization:
                uri, headers, body, status = self.create_authorization_response(
                    request=self.request, scopes=" ".join(scopes),
                    credentials=credentials, allow=True)
                return HttpResponseUriRedirect(uri, application.get_allowed_schemes())

            # *** Changed the if statement that checked for require_approval to an assert.
            assert require_approval == 'auto_even_if_expired'
            tokens = get_access_token_model().objects.filter(
                user=request.user,
                application=kwargs['application'],
                # *** Purposefully keeping this commented out code to highlight that
                # our version of the implementation does NOT filter by expiration date.
                # expires__gt=timezone.now(),
            ).all()

            # check past authorizations regarded the same scopes as the current one
            for token in tokens:
                if token.allow_scopes(scopes):
                    uri, headers, body, status = self.create_authorization_response(
                        request=self.request, scopes=" ".join(scopes),
                        credentials=credentials, allow=True)
                    return HttpResponseUriRedirect(uri, application.get_allowed_schemes())

            # render an authorization prompt so the user can approve
            # the application's requested scopes
            return self.render_to_response(self.get_context_data(**kwargs))

        except OAuthToolkitError as error:
            return self.error_response(error)
