"""Home Assistant Ingress path support."""
import os
import re

from werkzeug.exceptions import BadRequest, Forbidden


_PATH = re.compile(r'^/[A-Za-z0-9._~/-]+$')


class IngressPathMiddleware:
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        prefix = environ.get('HTTP_X_INGRESS_PATH')
        if os.getenv('WEBCLOCK_INGRESS') != '1' or not prefix:
            return self.application(environ, start_response)
        if environ.get('REMOTE_ADDR') != os.getenv('WEBCLOCK_INGRESS_PROXY', '172.30.32.2'):
            return Forbidden('Untrusted ingress proxy')(environ, start_response)
        if (len(prefix) > 512 or not _PATH.fullmatch(prefix) or '//' in prefix
                or any(part in ('.', '..') for part in prefix.split('/'))):
            return BadRequest('Invalid ingress path')(environ, start_response)
        environ['SCRIPT_NAME'] = prefix.rstrip('/')
        return self.application(environ, start_response)
