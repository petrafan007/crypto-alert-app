import tempfile
import unittest
from pathlib import Path
from flask import Flask
from routes.helpers import serve_react_app


class FrontendAssetIdentityTests(unittest.TestCase):
    def test_html_keeps_canonical_module_urls_and_disables_html_caching(self):
        html = '<script type="module" src="/static/assets/index-abc123.js"></script><link rel="modulepreload" href="/static/assets/vendor-def456.js">'
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'index.html').write_text(html)
            app = Flask(__name__, static_folder=directory)
            with app.test_request_context('/login'):
                response = serve_react_app()
                self.assertEqual(response.get_data(as_text=True), html)
                self.assertIn('no-store', response.headers['Cache-Control'])
                self.assertEqual(response.headers['Pragma'], 'no-cache')
                self.assertEqual(response.headers['Expires'], '0')
