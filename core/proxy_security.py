"""Reverse-proxy and browser-cookie hardening for the public dashboard."""

from ipaddress import ip_address

from werkzeug.middleware.proxy_fix import ProxyFix


class LoopbackProxyFix:
    """Trust forwarded scheme/host values only from the local tunnel process."""

    def __init__(self, app):
        self.direct_app = app
        self.proxy_app = ProxyFix(app, x_proto=1, x_host=1)

    def __call__(self, environ, start_response):
        remote_address = environ.get("REMOTE_ADDR", "")
        try:
            from_loopback = ip_address(remote_address).is_loopback
        except ValueError:
            from_loopback = False
        target = self.proxy_app if from_loopback else self.direct_app
        return target(environ, start_response)


def configure_public_proxy_security(app):
    """Apply the dashboard's production proxy and cookie security policy."""

    app.wsgi_app = LoopbackProxyFix(app.wsgi_app)
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=True,
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
    )
