"""Release channels follow SemVer and only offer complete public releases."""
import io
import json
import unittest
import urllib.error

from scripts.release_versions import API_URL, REPOSITORY, discover_release, parse_version


def release(version, **changes):
    tag = 'v' + version
    base = REPOSITORY + '/releases/download/' + tag + '/'
    result = {
        'tag_name': tag, 'draft': False, 'prerelease': '-' in version,
        'published_at': '2026-10-13T00:00:00Z', 'body': 'Release notes',
        'assets': [{'name': name, 'state': 'uploaded', 'size': 100,
                    'browser_download_url': base + name}
                   for name in ('webclock-' + version + '.tar.gz', 'SHA256SUMS')],
    }
    result.update(changes)
    return result


class ReleaseVersionsTest(unittest.TestCase):
    def opener(self, values, next_page=False):
        def open_url(request, timeout):
            self.assertTrue(request.full_url.startswith(API_URL + '?per_page=100&page='))
            self.assertEqual(timeout, 20)
            stream = io.BytesIO(json.dumps(values).encode())
            stream.headers = {'Link': '<https://unexpected.example/>; rel="next"'} if next_page else {}
            return stream
        return open_url

    def test_semver_orders_numeric_identifiers_stable_and_build_metadata(self):
        versions = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta',
                    '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0', '1.0.1', '1.10.0']
        self.assertEqual(sorted(reversed(versions), key=parse_version), versions)
        self.assertEqual(parse_version('1.0.0+build.1'), parse_version('1.0.0+other'))
        for invalid in ('1.0', '01.0.0', '1.0.0-beta.01', 'v1.0.0', '../main', '1.0.0-',
                        '1.0.0-β', '1.0.0-rc..1', '1.0.0+build..1', None, 1):
            with self.subTest(version=invalid), self.assertRaises(ValueError):
                parse_version(invalid)

    def test_stable_excludes_prerelease_flag_and_prerelease_version(self):
        values = [release('1.1.1'), release('2.0.0-beta.1', prerelease=False),
                  release('1.9.0', prerelease=True), release('1.2.0')]
        result = discover_release('stable', '1.1.0', self.opener(values))
        self.assertEqual(result['latest_version'], '1.2.0')
        self.assertTrue(result['update_available'])
        self.assertFalse(result['prerelease'])
        self.assertEqual(result['tag_name'], 'v1.2.0')
        self.assertEqual(result['html_url'], REPOSITORY + '/releases/tag/v1.2.0')

    def test_beta_includes_stable_and_never_downgrades(self):
        values = [release('1.2.0-beta.2'), release('1.2.0-beta.10'), release('1.1.5')]
        result = discover_release('beta', '1.2.0-beta.9', self.opener(values))
        self.assertEqual(result['latest_version'], '1.2.0-beta.10')
        self.assertTrue(result['update_available'])
        result = discover_release('beta', '1.2.0-beta.10', self.opener(values + [release('1.2.0')]))
        self.assertEqual(result['latest_version'], '1.2.0')
        self.assertFalse(result['prerelease'])
        for current in ('1.2.0', '1.3.0-beta.1', '1.3.0'):
            with self.subTest(current=current):
                result = discover_release('stable', current, self.opener([release('1.2.0')]))
                self.assertFalse(result['update_available'])

    def test_incomplete_malformed_drafts_and_unsafe_asset_urls_are_ignored(self):
        wrong_host = release('2.0.0')
        wrong_host['assets'][0]['browser_download_url'] = 'https://example.test/payload'
        empty_asset = release('2.1.0')
        empty_asset['assets'][0]['size'] = 0
        pending_asset = release('2.2.0')
        pending_asset['assets'][1]['state'] = 'new'
        values = [None, 'bad', release('3.0.0', draft=True), release('../main'),
                  release('3.0.1', published_at=None), release('3.0.2', assets=[]),
                  release('3.0.5', published_at={'bad': 'timestamp'}),
                  release('3.0.3', draft='false'), release('3.0.4', prerelease='false'),
                  wrong_host, empty_asset, pending_asset]
        result = discover_release('beta', '1.1.0', self.opener(values))
        self.assertFalse(result['update_available'])
        self.assertIsNone(result['latest_version'])

    def test_pagination_uses_fixed_api_origin_and_semver_instead_of_date_order(self):
        calls = []
        def opener(request, timeout):
            calls.append(request.full_url)
            return self.opener([release('1.1.2')] if len(calls) == 1 else [release('1.9.0')],
                               next_page=len(calls) == 1)(request, timeout)
        result = discover_release('stable', '1.1.0', opener)
        self.assertEqual(result['latest_version'], '1.9.0')
        self.assertEqual(calls, [API_URL + '?per_page=100&page=1', API_URL + '?per_page=100&page=2'])

    def test_network_invalid_response_and_channel_errors_are_explicit(self):
        error = urllib.error.HTTPError(API_URL, 403, 'rate limited', {}, io.BytesIO())
        self.addCleanup(error.close)
        def failed(request, timeout):
            raise error
        with self.assertRaisesRegex(RuntimeError, 'rate limited'):
            discover_release('stable', '1.1.0', failed)
        with self.assertRaisesRegex(RuntimeError, 'invalid release list'):
            discover_release('stable', '1.1.0', self.opener({}))
        with self.assertRaisesRegex(ValueError, 'channel'):
            discover_release('nightly', '1.1.0', self.opener([]))


if __name__ == '__main__':
    unittest.main()
