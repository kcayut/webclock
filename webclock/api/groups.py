"""Group management API; the application provides the authenticated owner."""
from flask import Blueprint, jsonify, request

from webclock.services.device_access_service import AccessError


def groups_api(service_provider, owner_id_provider, catalog_provider=None, member_observations=None):
    api = Blueprint('groups', __name__)

    @api.errorhandler(AccessError)
    def access_error(error):
        response = jsonify(error=str(error), code=error.code)
        response.status_code = error.status
        if error.retry_after is not None:
            response.headers['Retry-After'] = str(error.retry_after)
        return response

    @api.errorhandler(ValueError)
    @api.errorhandler(TypeError)
    def invalid(error):
        return jsonify(error='Invalid group or invitation request', code='invalid_request'), 400

    @api.errorhandler(OSError)
    def storage_failed(error):
        return jsonify(error='Storage failed; previous data has been retained', code='storage_failed'), 500

    @api.route('/api/v1/groups', methods=['GET', 'POST'])
    def groups():
        service, owner = service_provider(), owner_id_provider()
        if request.method == 'POST':
            return jsonify(service.create_group(owner, request.get_json())), 201
        return jsonify(groups=service.list_groups(owner))

    @api.route('/api/v1/groups/initialize', methods=['POST'])
    def initialize():
        data = request.get_json()
        if not isinstance(data, dict) or set(data) - {'name'}:
            raise ValueError('Expected initialization options')
        return jsonify(service_provider().initialize_owner(owner_id_provider(), **data))

    @api.route('/api/v1/groups/catalog')
    def catalog():
        # The root access guard checks the session; keep an explicit owner check
        # when this blueprint is reused by a different application factory.
        service_provider().list_groups(owner_id_provider())
        if catalog_provider is None:
            raise AccessError('Group catalog is unavailable', 503, 'catalog_not_ready')
        value = catalog_provider()
        return jsonify(defaults=value['defaults'],
                       calendar_sources=[{key: row[key] for key in ('id', 'name')} for row in value['calendar_sources']],
                       manual_notes=[{key: row[key] for key in ('id', 'text')} for row in value['manual_notes']],
                       schedules=[{key: row[key] for key in ('id', 'name')} for row in value['schedules']])

    @api.route('/api/v1/groups/<group_id>/members')
    def members(group_id):
        service, owner = service_provider(), owner_id_provider()
        rows = service.list_members(owner, group_id)
        observed = {row['id']: row for row in member_observations()} if member_observations else {}
        fields = ('name', 'online', 'last_seen', 'device_type', 'capabilities')
        return jsonify(members=[dict(row, **{key: observed.get(row.get('id', row.get('device_id')), {}).get(key)
                                             for key in fields}) for row in rows])

    @api.route('/api/v1/groups/<group_id>', methods=['GET', 'PATCH', 'DELETE'])
    def group(group_id):
        service, owner = service_provider(), owner_id_provider()
        if request.method == 'PATCH':
            return jsonify(service.update_group(owner, group_id, request.get_json()))
        if request.method == 'DELETE':
            service.delete_group(owner, group_id)
            return jsonify(status='deleted')
        return jsonify(service.get_group(owner, group_id))

    @api.route('/api/v1/groups/<group_id>/invite', methods=['GET', 'POST', 'DELETE'])
    def invite(group_id):
        service, owner = service_provider(), owner_id_provider()
        if request.method == 'POST':
            data = request.get_json()
            if not isinstance(data, dict) or set(data) - {'capacity'}:
                raise ValueError('Expected invitation options')
            return jsonify(service.create_invite(owner, group_id, **data)), 201
        if request.method == 'DELETE':
            return jsonify(invite=service.close_invite(owner, group_id))
        return jsonify(invite=service.get_invite(owner, group_id))

    return api
