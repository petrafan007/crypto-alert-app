"""PWA installability tests for the Crypto & Securities Dashboard.

Covers the manifest, service worker, icons, HTML meta links, SW
registration, and the public Flask routes that serve the manifest and
service worker at root scope.

The Flask route checks are skipped when the built dist/ copies are absent
(run `npm run build` in frontend/ first; upgrade.sh always builds before
restarting, so deployed copies always exist).
"""
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend" / "public"
DIST = ROOT / "frontend" / "dist"


def png_size(path):
    with open(path, "rb") as f:
        data = f.read(33)
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class PwaFilesTests(unittest.TestCase):
    def test_manifest_is_valid_and_installable(self):
        manifest_path = PUBLIC / "manifest.webmanifest"
        self.assertTrue(manifest_path.exists(), "manifest.webmanifest missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "Crypto & Securities Dashboard")
        self.assertTrue(manifest["short_name"])
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue(manifest["theme_color"])
        self.assertTrue(manifest["background_color"])
        by_size = {i["sizes"]: i for i in manifest["icons"]}
        self.assertIn("192x192", by_size)
        self.assertIn("512x512", by_size)
        self.assertTrue(
            any(i.get("purpose") == "maskable" for i in manifest["icons"]),
            "manifest needs a maskable icon",
        )
        self.assertTrue(
            any(i["sizes"] == "180x180" for i in manifest["icons"]),
            "manifest needs a 180x180 Apple touch icon",
        )

    def test_icons_exist_and_are_correct_sizes(self):
        expected = {
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "icon-maskable-512.png": (512, 512),
            "apple-touch-icon.png": (180, 180),
        }
        for name, size in expected.items():
            path = PUBLIC / "icons" / name
            self.assertTrue(path.exists(), f"{name} missing")
            self.assertEqual(png_size(path), size, f"{name} wrong size")

    def test_service_worker_never_caches_api_traffic(self):
        sw = (PUBLIC / "sw.js").read_text(encoding="utf-8")
        self.assertIn("csdapp-v1", sw)
        self.assertIn("if (url.pathname.startsWith('/api/')) return;", sw)
        self.assertIn("caches.match", sw)
        self.assertIn("self.skipWaiting()", sw)

    def test_index_html_links_manifest_and_ios_meta(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('rel="manifest" href="/manifest.webmanifest"', html)
        self.assertIn('name="theme-color"', html)
        self.assertIn('name="apple-mobile-web-app-capable"', html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn("apple-touch-icon.png", html)

    def test_main_registers_service_worker(self):
        main = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        self.assertIn("serviceWorker.register('/sw.js')", main)


@unittest.skipUnless(
    (DIST / "sw.js").exists() and (DIST / "manifest.webmanifest").exists(),
    "dist/ PWA files absent; run `npm run build` in frontend/ first",
)
class PwaRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask

        from routes.frontend import frontend_bp

        cls.app = Flask(__name__, static_folder=str(DIST))
        cls.app.config.update(SECRET_KEY="pwa-test", TESTING=True)
        cls.app.register_blueprint(frontend_bp)
        cls.client = cls.app.test_client()

    def test_sw_js_served_at_root_with_js_mime(self):
        resp = self.client.get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("javascript", resp.content_type)
        self.assertIn(b"csdapp-v1", resp.data)
        self.assertEqual(resp.headers.get("Service-Worker-Allowed"), "/")

    def test_manifest_served_at_root_with_manifest_mime(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/manifest+json", resp.content_type)
        manifest = json.loads(resp.data)
        self.assertEqual(manifest["display"], "standalone")

    def test_manifest_and_sw_are_public_without_login(self):
        # No session cookie is set on self.client; a login redirect (302)
        # here would mean the routes wrongly require authentication.
        self.assertEqual(self.client.get("/sw.js").status_code, 200)
        self.assertEqual(self.client.get("/manifest.webmanifest").status_code, 200)


if __name__ == "__main__":
    unittest.main()
