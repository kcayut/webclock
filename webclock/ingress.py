"""Home Assistant Ingress path support."""
import os
import re

from werkzeug.exceptions import BadRequest, Forbidden, NotFound


_PATH = re.compile(r'^/[A-Za-z0-9._~/-]+$')
_DISPLAY_PATHS = frozenset(('/', '/sw.js', '/api/health', '/api/time', '/api/csrf'))
_DISPLAY_PREFIXES = ('/static/', '/api/v1/device/', '/api/v2/device/', '/api/v1/control/')


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
        environ['SCRIPT_NAME'] = prefix.rstrip('/')
        environ['webclock.surface'] = 'ingress'
        return self.application(environ, start_response)
