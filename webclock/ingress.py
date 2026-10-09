"""Home Assistant Ingress path support."""
import os
import re
from ipaddress import IPv6Address

from werkzeug.exceptions import BadRequest, Forbidden, NotFound


_PATH = re.compile(r'^/[A-Za-z0-9._~/-]+$')
_HOST = re.compile(r'(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::([0-9]{1,5}))?')
_HOST_LABEL = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?')
_DISPLAY_PATHS = frozenset(('/', '/sw.js', '/api/health', '/api/time', '/api/csrf'))
_DISPLAY_PREFIXES = ('/static/', '/api/v1/device/', '/api/v2/device/', '/api/v1/control/')


def _valid_forwarded_host(value):
    match = _HOST.fullmatch(value)
    if not match or (match[2] is not None and not 1 <= int(match[2]) <= 65535):
        return False
    hostname = match[1]
    if hostname.startswith('['):
        try:
            IPv6Address(hostname[1:-1])
        except ValueError:
            return False
        return True
    hostname = hostname.removesuffix('.')
    return len(hostname) <= 253 and all(
        _HOST_LABEL.fullmatch(label) for label in hostname.split('.'))


def _display_path_allowed(path):
    if path in _DISPLAY_PATHS:
        return True
    if (len(path) > 512 or not _PATH.fullmatch(path) or '//' in path
            or any(part in ('.', '..') for part in path.split('/'))):
        return False
    return any(path.startswith(prefix) for prefix in _DISPLAY_PREFIXES)


class IngressPathMiddleware:
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        prefix = environ.get('HTTP_X_INGRESS_PATH')
        if os.getenv('WEBCLOCK_HA_APP') == '1':
            port = environ.get('SERVER_PORT')
            if port == os.getenv('WEBCLOCK_DISPLAY_PORT', '8100'):
                if prefix or not _display_path_allowed(environ.get('PATH_INFO', '/')):
                    return NotFound()(environ, start_response)
                environ['webclock.surface'] = 'display'
                return self.application(environ, start_response)
            if port != os.getenv('WEBCLOCK_INGRESS_PORT', '8099') or not prefix:
                return Forbidden('Ingress is required')(environ, start_response)
        if os.getenv('WEBCLOCK_INGRESS') != '1' or not prefix:
            return self.application(environ, start_response)
        if environ.get('REMOTE_ADDR') != os.getenv('WEBCLOCK_INGRESS_PROXY', '172.30.32.2'):
            return Forbidden('Untrusted ingress proxy')(environ, start_response)
        if (len(prefix) > 512 or not _PATH.fullmatch(prefix) or '//' in prefix
                or any(part in ('.', '..') for part in prefix.split('/'))):
            return BadRequest('Invalid ingress path')(environ, start_response)
        scheme = environ.get('HTTP_X_FORWARDED_PROTO')
        host = environ.get('HTTP_X_FORWARDED_HOST')
        if (scheme not in (None, 'http', 'https')
                or (host is not None and not _valid_forwarded_host(host))):
            return BadRequest('Invalid ingress origin')(environ, start_response)
        # Only the trusted HA Ingress proxy may restore the browser's origin.
        if scheme is not None:
            environ['wsgi.url_scheme'] = scheme
        if host is not None:
            environ['HTTP_HOST'] = host
        environ['SCRIPT_NAME'] = prefix.rstrip('/')
        environ['webclock.surface'] = 'ingress'
        return self.application(environ, start_response)
