"""
Middleware for handling CSRF checks with CORS requests


CSRF and referrer domain checks
-------------------------------

When processing HTTPS requests, the default CSRF middleware checks that the referer
domain and protocol is the same as the request's domain and protocol. This is meant
to avoid a type of attack for sites which serve their content with both HTTP and HTTPS,
with a man in the middle on the HTTP requests.

https://github.com/django/django/blob/b91c385e324f1cb94d20e2ad146372c259d51d3b/django/middleware/csrf.py#L117

This doesn't work well with CORS requests, which aren't vulnerable to this attack when
the server from which the request is coming uses HTTPS too, as it prevents the man in the
middle attack vector.

We thus do the CSRF check of requests coming from an authorized CORS host separately
in this middleware, applying the same protections as the default CSRF middleware, but
without the referrer check, when both the request and the referer use HTTPS.


CSRF cookie domains
-------------------

In addition, in order to make cross-domain AJAX calls to CSRF-protected end-points,
we need to send the CSRF token in the HTTP header of the request.

The simple way to do this would be to set the CSRF_COOKIE_DOMAIN to ".edx.org",
but unfortunately this can cause problems.  For example, suppose that
"first.edx.org" sets the cookie with domain ".edx.org", but "second.edx.org"
sets a cookie with domain "second.edx.org".  In this case, the browser
would have two different CSRF tokens set (one for each cookie domain),
which can cause non-deterministic failures depending on which cookie
is sent first.

For this reason, we add a second cookie that (a) has the domain set to ".edx.org",
but (b) does NOT have the same name as the CSRF_COOKIE_NAME.  Clients making
cross-domain requests can use this cookie instead of the subdomain-specific
CSRF cookie.

"""

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed
from django.middleware import csrf as django_csrf
from .helpers import is_cross_domain_request_allowed, skip_cross_domain_referer_check, same_origin
from django.utils.crypto import constant_time_compare
from django.utils.encoding import force_text

log = logging.getLogger(__name__)

REASON_BAD_REFERER = "Referer checking failed - %s does not match any trusted origins."


class CsrfCrossDomainCookieMiddleware(object):
    """Set an additional "cross-domain" CSRF cookie.

    Usage:

        1) Decorate a view with `@ensure_csrf_cookie_cross_domain`.
        2) Set `CROSS_DOMAIN_CSRF_COOKIE_NAME` and `CROSS_DOMAIN_CSRF_COOKIE_DOMAIN`
            in settings.
        3) Add the domain to `CORS_ORIGIN_WHITELIST`
        4) Enable `FEATURES['ENABLE_CROSS_DOMAIN_CSRF_COOKIE']`

    For testing, it is often easier to relax the security checks by setting:
        * `CORS_ALLOW_INSECURE = True`
        * `CORS_ORIGIN_ALLOW_ALL = True`

    """

    def __init__(self):
        """Disable the middleware if the feature is not enabled. """
        if not settings.FEATURES.get('ENABLE_CROSS_DOMAIN_CSRF_COOKIE'):
            raise MiddlewareNotUsed()

        if not getattr(settings, 'CROSS_DOMAIN_CSRF_COOKIE_NAME', ''):
            raise ImproperlyConfigured(
                "You must set `CROSS_DOMAIN_CSRF_COOKIE_NAME` when "
                "`FEATURES['ENABLE_CROSS_DOMAIN_CSRF_COOKIE']` is True."
            )

        if not getattr(settings, 'CROSS_DOMAIN_CSRF_COOKIE_DOMAIN', ''):
            raise ImproperlyConfigured(
                "You must set `CROSS_DOMAIN_CSRF_COOKIE_DOMAIN` when "
                "`FEATURES['ENABLE_CROSS_DOMAIN_CSRF_COOKIE']` is True."
            )

    def process_response(self, request, response):
        """Set the cross-domain CSRF cookie. """

        # Check whether this is a secure request from a domain on our whitelist.
        if not is_cross_domain_request_allowed(request):
            log.debug("Could not set cross-domain CSRF cookie.")
            return response

        # Check whether (a) the CSRF middleware has already set a cookie, and
        # (b) this is a view decorated with `@ensure_cross_domain_csrf_cookie`
        # If so, we can send the cross-domain CSRF cookie.
        should_set_cookie = (
            request.META.get('CROSS_DOMAIN_CSRF_COOKIE_USED', False) and
            request.META.get('CSRF_COOKIE_USED', False) and
            request.META.get('CSRF_COOKIE') is not None
        )

        if should_set_cookie:
            # This is very similar to the code in Django's CSRF middleware
            # implementation, with two exceptions:
            # 1) We change the cookie name and domain so it can be used cross-domain.
            # 2) We always set "secure" to True, so that the CSRF token must be
            # sent over a secure connection.
            response.set_cookie(
                settings.CROSS_DOMAIN_CSRF_COOKIE_NAME,
                request.META['CSRF_COOKIE'],
                max_age=settings.CSRF_COOKIE_AGE,
                domain=settings.CROSS_DOMAIN_CSRF_COOKIE_DOMAIN,
                path=settings.CSRF_COOKIE_PATH,
                secure=True
            )
            log.debug(
                "Set cross-domain CSRF cookie '%s' for domain '%s'",
                settings.CROSS_DOMAIN_CSRF_COOKIE_NAME,
                settings.CROSS_DOMAIN_CSRF_COOKIE_DOMAIN
            )

        return response


class CrossDomainCsrfViewMiddleware(django_csrf.CsrfViewMiddleware):

    def process_view(self, request, callback, callback_args, callback_kwargs):

        if getattr(request, 'csrf_processing_done', False):
            return None

        try:
            csrf_token = django_csrf._sanitize_token(
                request.COOKIES[settings.CSRF_COOKIE_NAME])
            # Use same token next time
            request.META['CSRF_COOKIE'] = csrf_token
        except KeyError:
            csrf_token = None
            # Generate token and store it in the request, so it's
            # available to the view.
            request.META["CSRF_COOKIE"] = django_csrf._get_new_csrf_string()

        # Wait until request.META["CSRF_COOKIE"] has been manipulated before
        # bailing out, so that get_token still works
        if getattr(callback, 'csrf_exempt', False):
            return None

        # Assume that anything not defined as 'safe' by RFC2616 needs protection
        if request.method not in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
            if getattr(request, '_dont_enforce_csrf_checks', False):
                # Mechanism to turn off CSRF checks for test suite.
                # It comes after the creation of CSRF cookies, so that
                # everything else continues to work exactly the same
                # (e.g. cookies are sent, etc.), but before any
                # branches that call reject().
                return self._accept(request)

            if request.is_secure():
                # Suppose user visits http://example.com/
                # An active network attacker (man-in-the-middle, MITM) sends a
                # POST form that targets https://example.com/detonate-bomb/ and
                # submits it via JavaScript.
                #
                # The attacker will need to provide a CSRF cookie and token, but
                # that's no problem for a MITM and the session-independent
                # nonce we're using. So the MITM can circumvent the CSRF
                # protection. This is true for any HTTP connection, but anyone
                # using HTTPS expects better! For this reason, for
                # https://example.com/ we need additional protection that treats
                # http://example.com/ as completely untrusted. Under HTTPS,
                # Barth et al. found that the Referer header is missing for
                # same-domain requests in only about 0.2% of cases or less, so
                # we can use strict Referer checking.
                referer = force_text(
                    request.META.get('HTTP_REFERER'),
                    strings_only=True,
                    errors='replace'
                )
                if referer is None:
                    return self._reject(request, django_csrf.REASON_NO_REFERER)

                # Here we generate a list of all acceptable HTTP referers,
                # including the current host since that has been validated
                # upstream.
                good_hosts = list(settings.CSRF_TRUSTED_ORIGINS)
                # Note that request.get_host() includes the port.
                good_hosts.append(request.get_host())
                good_referers = ['https://{0}/'.format(host) for host in good_hosts]
                if not any(same_origin(referer, host) for host in good_referers):
                    reason = REASON_BAD_REFERER % referer
                    return self._reject(request, reason)

            if csrf_token is None:
                # No CSRF cookie. For POST requests, we insist on a CSRF cookie,
                # and in this way we can avoid all CSRF attacks, including login
                # CSRF.
                return self._reject(request, django_csrf.REASON_NO_CSRF_COOKIE)

            # Check non-cookie token for match.
            request_csrf_token = ""
            if request.method == "POST":
                try:
                    request_csrf_token = request.POST.get('csrfmiddlewaretoken', '')
                except IOError:
                    # Handle a broken connection before we've completed reading
                    # the POST data. process_view shouldn't raise any
                    # exceptions, so we'll ignore and serve the user a 403
                    # (assuming they're still listening, which they probably
                    # aren't because of the error).
                    pass

            if request_csrf_token == "":
                # Fall back to X-CSRFToken, to make things easier for AJAX,
                # and possible for PUT/DELETE.
                request_csrf_token = request.META.get('HTTP_X_CSRFTOKEN', '')

            if not constant_time_compare(request_csrf_token, csrf_token):
                return self._reject(request, django_csrf.REASON_BAD_TOKEN)

        return self._accept(request)


class CorsCSRFMiddleware(CrossDomainCsrfViewMiddleware):
    """
    Middleware for handling CSRF checks with CORS requests
    """
    def __init__(self):
        """Disable the middleware if the feature flag is disabled. """
        if not settings.FEATURES.get('ENABLE_CORS_HEADERS'):
            raise MiddlewareNotUsed()

    def process_view(self, request, callback, callback_args, callback_kwargs):
        """Skip the usual CSRF referer check if this is an allowed cross-domain request. """
        if not is_cross_domain_request_allowed(request):
            log.debug("Could not disable CSRF middleware referer check for cross-domain request.")
            return

        with skip_cross_domain_referer_check(request):
            return super(CorsCSRFMiddleware, self).process_view(request, callback, callback_args, callback_kwargs)
