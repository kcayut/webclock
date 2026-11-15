import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def png_size(path):
    data = path.read_bytes()[:24]
    if data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise AssertionError(f'{path} is not a PNG')
    return struct.unpack('>II', data[16:24])


class PwaManifestTest(unittest.TestCase):
    def test_manifest_links_and_icons(self):
        manifest = json.loads((ROOT / 'static/manifest.json').read_text())
        self.assertEqual(manifest['name'], 'WebClock')
        self.assertEqual(manifest['short_name'], 'WebClock')
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['start_url'], '../')
        self.assertEqual(manifest['scope'], '../')
        self.assertEqual(manifest['background_color'], '#000000')
        self.assertEqual(manifest['theme_color'], '#000000')

        purposes = {}
        for icon in manifest['icons']:
            path = ROOT / 'static' / icon['src']
            self.assertTrue(path.is_file(), icon['src'])
            width, height = png_size(path)
            self.assertEqual(icon['sizes'], f'{width}x{height}', icon['src'])
            self.assertEqual(icon['type'], 'image/png')
            purposes.setdefault(icon['purpose'], []).append(width)
        self.assertIn(192, purposes['any'])
        self.assertIn(512, purposes['any'])
        self.assertEqual(purposes['maskable'], [512])

        brand_head = (ROOT / 'templates/brand_head.html').read_text()
        self.assertIn("filename='manifest.json'", brand_head)
        self.assertIn('rel="manifest"', brand_head)
        self.assertIn('apple-mobile-web-app-capable', brand_head)
        public_index = (ROOT / 'index.html').read_text()
        self.assertIn('rel="manifest"', public_index)
        self.assertIn('static/manifest.json', public_index)
        build_release = (ROOT / 'tools/build_release.py').read_text()
        self.assertIn("'static/manifest.json'", build_release)


if __name__ == '__main__':
    unittest.main()
