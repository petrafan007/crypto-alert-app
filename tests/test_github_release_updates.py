import unittest
from unittest.mock import Mock, patch

from routes.system import fetch_latest_github_release


class GitHubReleaseUpdateTests(unittest.TestCase):
    @staticmethod
    def release_response(releases):
        response = Mock()
        response.json.return_value = releases
        response.raise_for_status.return_value = None
        return response

    def test_latest_stable_release_ignores_prereleases_and_drafts(self):
        response = self.release_response([
            {
                'tag_name': 'v2.23.0-beta.1',
                'prerelease': True,
                'draft': False,
                'published_at': '2026-08-28T12:00:00Z',
            },
            {
                'tag_name': 'v2.22.3',
                'prerelease': False,
                'draft': False,
                'published_at': '2026-08-27T12:00:00Z',
            },
            {
                'tag_name': 'v9.0.0',
                'prerelease': False,
                'draft': True,
                'published_at': '2026-08-29T12:00:00Z',
            },
        ])

        with patch('routes.system.requests.get', return_value=response) as get:
            release = fetch_latest_github_release(include_beta=False)

        self.assertEqual(release['tag_name'], 'v2.22.3')
        self.assertEqual(get.call_args.kwargs['params'], {'per_page': 100})

    def test_latest_release_includes_prereleases_when_enabled(self):
        response = self.release_response([
            {
                'tag_name': 'v2.22.3',
                'prerelease': False,
                'draft': False,
                'published_at': '2026-08-27T12:00:00Z',
            },
            {
                'tag_name': 'v2.23.0-beta.1',
                'prerelease': True,
                'draft': False,
                'published_at': '2026-08-28T12:00:00Z',
            },
        ])

        with patch('routes.system.requests.get', return_value=response):
            release = fetch_latest_github_release(include_beta=True)

        self.assertEqual(release['tag_name'], 'v2.23.0-beta.1')

    def test_missing_eligible_releases_is_reported(self):
        response = self.release_response([
            {
                'tag_name': 'v2.23.0-beta.1',
                'prerelease': True,
                'draft': False,
                'published_at': '2026-08-28T12:00:00Z',
            },
        ])

        with patch('routes.system.requests.get', return_value=response):
            with self.assertRaises(LookupError):
                fetch_latest_github_release(include_beta=False)
