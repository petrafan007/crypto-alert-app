import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, jsonify, request, session, url_for

from core.proxy_security import configure_public_proxy_security
from routes.system import system_bp


class ProxySecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = "proxy-security-test-key"

        @self.app.get("/probe")
        def probe():
            return jsonify({
                "scheme": request.scheme,
                "host": request.host,
                "external_url": url_for("probe", _external=True),
            })

        @self.app.get("/set-session")
        def set_session():
            session["authenticated"] = True
            return "ok"

        configure_public_proxy_security(self.app)
        self.client = self.app.test_client()

    def test_loopback_tunnel_headers_supply_public_https_origin(self):
        response = self.client.get(
            "/probe",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "csdapp.online",
            },
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

        self.assertEqual(response.get_json(), {
            "scheme": "https",
            "host": "csdapp.online",
            "external_url": "https://csdapp.online/probe",
        })

    def test_direct_lan_request_cannot_spoof_forwarded_origin(self):
        response = self.client.get(
            "/probe",
            base_url="http://192.168.1.253:5010",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "attacker.example",
            },
            environ_base={"REMOTE_ADDR": "192.168.1.50"},
        )

        self.assertEqual(response.get_json(), {
            "scheme": "http",
            "host": "192.168.1.253:5010",
            "external_url": "http://192.168.1.253:5010/probe",
        })

    def test_session_and_remember_cookie_policy_is_secure(self):
        response = self.client.get("/set-session", base_url="https://csdapp.online")
        cookie = response.headers["Set-Cookie"]

        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertTrue(self.app.config["REMEMBER_COOKIE_SECURE"])
        self.assertTrue(self.app.config["REMEMBER_COOKIE_HTTPONLY"])
        self.assertEqual(self.app.config["REMEMBER_COOKIE_SAMESITE"], "Lax")

    def test_desktop_download_url_uses_forwarded_https_origin(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "desktop-url-test-key"
        app.register_blueprint(system_bp)
        configure_public_proxy_security(app)

        with patch(
            "routes.system.get_user_from_desktop_session",
            return_value=SimpleNamespace(username="test-user"),
        ):
            response = app.test_client().get(
                "/api/desktop/check-update?current_version=1.0.0",
                headers={
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "csdapp.online",
                },
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )

        self.assertEqual(
            response.get_json()["download_url"],
            "https://csdapp.online/api/desktop/download-update",
        )


if __name__ == "__main__":
    unittest.main()
