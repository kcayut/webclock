"""Discover complete, published WebClock releases without a maintained version feed."""
import json
import re
import urllib.error
import urllib.request


REPOSITORY = 'https://github.com/kcayut/webclock'
API_URL = 'https://api.github.com/repos/kcayut/webclock/releases'
VERSION_PATTERN = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'


def parse_version(value):
    """Return SemVer precedence; build metadata does not change precedence."""
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError('Invalid semantic version')
    match = re.fullmatch(VERSION_PATTERN + r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?', value)
    if match is None:
        raise ValueError('Invalid semantic version: ' + value)
    major, minor, patch, prerelease = match.groups()
    identifiers = []
    for part in prerelease.split('.') if prerelease else ():
        if part.isdigit():
            if len(part) > 1 and part.startswith('0'):
                raise ValueError('Numeric prerelease identifiers cannot have leading zeros')
            identifiers.append((0, int(part)))
        else:
            identifiers.append((1, part))
    return int(major), int(minor), int(patch), prerelease is None, tuple(identifiers)


def release_version(value):
    """Release versions must also be valid container tags and asset filenames."""
    result = parse_version(value)
    if '+' in value:
        raise ValueError('Release versions cannot contain build metadata')
    return result


def discover_release(channel, current_version, opener=None):
    if channel not in ('stable', 'beta'):
        raise ValueError('Release channel must be stable or beta')
    current = parse_version(current_version)
    result = {
        'channel': channel, 'current_version': current_version,
        'latest_version': None, 'tag_name': None, 'html_url': None,
        'body': '', 'published_at': None, 'update_available': False,
        'prerelease': False, 'asset_name': None, 'download_url': None,
        'checksums_url': None,
    }
    latest = None
    open_url = opener or urllib.request.urlopen
    for page in range(1, 101):
        request = urllib.request.Request(API_URL + '?per_page=100&page=' + str(page), headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'WebClock-Updater',
        })
        try:
            with open_url(request, timeout=20) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise RuntimeError('GitHub release response is too large')
                releases = json.loads(raw)
                next_page = 'rel="next"' in getattr(response, 'headers', {}).get('Link', '')
        except urllib.error.HTTPError as error:
            if error.code in (403, 429):
                raise RuntimeError('GitHub release checks are rate limited; try again later') from error
            raise RuntimeError('GitHub release check failed (HTTP ' + str(error.code) + ')') from error
        except (OSError, ValueError) as error:
            raise RuntimeError('Could not read GitHub releases; try again later') from error
        if not isinstance(releases, list):
            raise RuntimeError('GitHub returned an invalid release list')
        for release in releases:
            if not isinstance(release, dict) or release.get('draft') is not False:
                continue
            if (not isinstance(release.get('prerelease'), bool)
                    or not isinstance(release.get('published_at'), str) or not release['published_at']):
                continue
            tag = release.get('tag_name')
            if not isinstance(tag, str) or not tag.startswith('v'):
                continue
            version = tag[1:]
            try:
                precedence = release_version(version)
            except ValueError:
                continue
            prerelease = release['prerelease'] or not precedence[3]
            if channel == 'stable' and prerelease:
                continue
            if latest is not None and precedence <= latest:
                continue
            asset_name = 'webclock-' + version + '.tar.gz'
            base = REPOSITORY + '/releases/download/' + tag + '/'
            assets = release.get('assets')
            if not isinstance(assets, list):
                continue
            ready = {asset.get('name') for asset in assets if isinstance(asset, dict)
                     and asset.get('state') == 'uploaded'
                     and type(asset.get('size')) is int and asset['size'] > 0
                     and isinstance(asset.get('name'), str)
                     and asset.get('browser_download_url') == base + asset['name']}
            if not {asset_name, 'SHA256SUMS'} <= ready:
                continue
            latest = precedence
            result.update({
                'latest_version': version, 'tag_name': tag,
                'html_url': REPOSITORY + '/releases/tag/' + tag,
                'body': release.get('body', '') if isinstance(release.get('body', ''), str) else '',
                'published_at': release['published_at'], 'update_available': precedence > current,
                'prerelease': prerelease, 'asset_name': asset_name,
                'download_url': base + asset_name, 'checksums_url': base + 'SHA256SUMS',
            })
        if not next_page:
            return result
    raise RuntimeError('GitHub release list exceeds the supported pagination limit')
