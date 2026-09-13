import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask

from routes.market import market_bp


class StockIconRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.app = Flask(__name__, instance_path=self.temp_dir)
        self.app.register_blueprint(market_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_invalid_symbols(self):
        resp = self.client.get('/api/stock-icon/$$$$$$$$$$$$$$$$$$$$$$$$')
        self.assertEqual(resp.status_code, 400)

    def test_cached_icon_on_disk_is_served_with_immutable_cache(self):
        cache_dir = os.path.join(self.temp_dir, 'stock_icons')
        os.makedirs(cache_dir, exist_ok=True)
        target = os.path.join(cache_dir, 'AAPL.png')
        with open(target, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'A' * 100)

        resp = self.client.get('/api/stock-icon/AAPL')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, 'image/png')
        self.assertEqual(resp.headers.get('Cache-Control'), 'public, max-age=31536000, immutable')
        self.assertTrue(resp.data.startswith(b'\x89PNG'))

    @patch('routes.market.requests.get')
    def test_fetches_and_persists_remote_icon(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'Content-Type': 'image/svg+xml'}
        mock_response.content = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>'
        mock_get.return_value = mock_response

        resp = self.client.get('/api/stock-icon/TSLA')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content_type.startswith('image/svg+xml'))
        self.assertEqual(resp.headers.get('Cache-Control'), 'public, max-age=31536000, immutable')

        # Verify saved to disk
        saved_file = os.path.join(self.temp_dir, 'stock_icons', 'TSLA.svg')
        self.assertTrue(os.path.exists(saved_file))
        with open(saved_file, 'rb') as f:
            self.assertEqual(f.read(), mock_response.content)

    @patch('routes.market.requests.get')
    def test_404_when_neither_source_finds_icon(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.content = b''
        mock_get.return_value = mock_response

        resp = self.client.get('/api/stock-icon/NONEXISTENT')
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
