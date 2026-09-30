"""Register management and device APIs with shared transport safeguards."""
import hmac
import os

from flask import Blueprint, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from .management import management_api
from .device import device_api


def register_api(app, state_directory, holidays, template_context, calendar_events=None, calendar_sources=None):
    api = Blueprint('server_api', __name__)
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024

    @api.before_request
    def protect():
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            abort(403, description='Cross-origin management access is not allowed')
        if request.path.startswith('/api/v1/device/'):
            token = os.getenv('DEVICE_API_TOKEN', '')
            if token and not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
                abort(401, description='A device API token is required')
        if request.is_json and request.content_length and request.content_length > 1024 * 1024:
            abort(413, description='JSON body is too large')

    @api.after_request
    def private_response(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers.setdefault('Cache-Control', 'no-store')
        return response

    @api.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @api.errorhandler(FileNotFoundError)
    @api.errorhandler(KeyError)
    def missing(error):
        return jsonify(error='Item not found'), 404

    @api.errorhandler(OSError)
    def failed_write(error):
        app.logger.exception('Management storage failed')
        return jsonify(error='Storage failed; previous data has been retained'), 500

    @api.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    api.register_blueprint(management_api(state_directory, holidays, template_context, calendar_events, calendar_sources))
    api.register_blueprint(device_api(state_directory, holidays))
    app.register_blueprint(api)
