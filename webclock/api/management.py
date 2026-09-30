"""Browser-facing schedule and device management routes."""
from datetime import datetime, timedelta
from pathlib import Path
import uuid

from flask import Blueprint, abort, jsonify, render_template, request

from webclock.services.device_service import DeviceService
from webclock.services.schedule_service import TAIPEI, read_schedules, save_schedules, validate_schedule, next_event, next_occurrence, prefetch_calendar_sources
from webclock.services.storage import storage_lock
from webclock.translations.schedules import SCHEDULE_TRANSLATIONS


def taipei_now():
    return datetime.now(TAIPEI)


def management_api(state_directory, holidays, template_context, calendar_events=None, calendar_sources=None):
    api = Blueprint('management', __name__)

    def schedules():
        return read_schedules(state_directory())

    def store(rows):
        save_schedules(state_directory(), rows)

    def devices():
        return DeviceService(Path(state_directory()) / 'devices.json')

    def source_catalog():
        sources = calendar_sources() if calendar_sources else []
        return [dict(id='local', name='本地提醒', provider='local')] + [
            {key: row[key] for key in ('id', 'name', 'provider')} for row in sources]

    def check_sources(row):
        link = row.get('calendar_link')
        if link and set(link['source_ids']) - {source['id'] for source in source_catalog()}:
            raise ValueError('Selected calendar source no longer exists')

    @api.route('/schedules')
    def management():
        context = template_context()
        return render_template('schedules.html', schedule_translations=SCHEDULE_TRANSLATIONS[context['language']], **context)

    @api.route('/api/v1/schedules', methods=['GET', 'POST'])
    def schedule_collection():
        with storage_lock:
            rows = schedules()
            if request.method == 'POST':
                data = request.get_json()
                if not isinstance(data, dict):
                    raise ValueError('Expected a schedule object')
                row = validate_schedule(dict(data, id=data.get('id', uuid.uuid4().hex)))
                check_sources(row)
                if len(rows) >= 1000 or any(item['id'] == row['id'] for item in rows):
                    raise ValueError('Duplicate schedule ID or schedule limit reached')
                rows.append(row)
                store(rows)
                return jsonify(row), 201
        # Calendar I/O must not hold the schedule storage lock.
        now = taipei_now()
        enriched, upcoming = [], []
        prefetch_calendar_sources(rows, now, calendar_events)
        for row in rows:
            event = next_occurrence(row, holidays, now, calendar_events)
            enriched.append(dict(row, next_occurrence=event['datetime'] if event else None))
            if event:
                upcoming.append(event)
        return jsonify(schedules=enriched,
                       next_event=min(upcoming, key=lambda event: (event['datetime'], event['id']), default=None),
                       calendar_sources=source_catalog(),
                       day=holidays.get_day_type(now.date()), server_time=now.isoformat(),
                       holiday_coverage=holidays.export()['coverage'], timezone='Asia/Taipei')

    @api.route('/api/v1/schedules/<schedule_id>', methods=['PUT', 'DELETE'])
    def schedule_item(schedule_id):
        with storage_lock:
            rows = schedules()
            old = next((row for row in rows if row['id'] == schedule_id), None)
            if old is None:
                abort(404)
            if request.method == 'DELETE':
                store([row for row in rows if row['id'] != schedule_id])
                return jsonify(status='deleted')
            data = request.get_json()
            if not isinstance(data, dict) or data.get('id', schedule_id) != schedule_id:
                raise ValueError('Invalid schedule object or ID')
            row = validate_schedule(dict(old, **data))
            if 'calendar_link' in data:
                check_sources(row)
            rows[rows.index(old)] = row
            store(rows)
            return jsonify(row)

    @api.route('/api/v1/browser-alarms')
    def browser_alarms():
        now = taipei_now()
        minute = now.replace(second=0, microsecond=0)
        rows = [row for row in schedules() if row['enabled'] and row['type'] == 'alarm']
        alarms = []
        windows = {}

        def lookup(start, end, source_ids):
            key = (start, end, tuple(source_ids))
            if key not in windows:
                windows[key] = calendar_events(start=start, end=end, source_ids=source_ids) if calendar_events else []
            return windows[key]

        prefetch_calendar_sources(rows, now, lookup)
        for row in rows:
            cursor = minute
            # Include this minute's linked events before the next future event,
            # so two events with different seconds are not collapsed into one.
            while len(alarms) < 1000:
                event = next_occurrence(row, holidays, cursor, lookup)
                if not event:
                    break
                stamp = datetime.fromisoformat(event['datetime'])
                alarms.append(dict(occurrence_id=event['occurrence_id'], id=event['id'],
                                   name=event['name'], sound=event['browser_sound'],
                                   starts_at=int(stamp.timestamp() * 1000)))
                if not row.get('calendar_link') or stamp > now:
                    break
                cursor = stamp + timedelta(microseconds=1)
        alarms.sort(key=lambda event: (event['starts_at'], event['id']))
        return jsonify(server_timestamp=int(taipei_now().timestamp() * 1000), enabled_count=len(rows),
                       enabled_ids=sorted(row['id'] for row in rows),
                       alarms=alarms, holiday_coverage=holidays.coverage,
                       holiday_known=holidays.get_day_type(now.date())['known'])

    @api.route('/api/v1/schedules/<schedule_id>/skip-next', methods=['POST'])
    def skip_next(schedule_id):
        with storage_lock:
            rows = schedules()
            row = next((row for row in rows if row['id'] == schedule_id), None)
            if row is None:
                abort(404)
            now = taipei_now()
            event = next_event([row], holidays, now, calendar_events)
            if event is None:
                raise ValueError('No upcoming occurrence to skip')
            skips = [value for value in row.get('skipped_occurrences', []) if datetime.fromisoformat(value) > now]
            row['skipped_occurrences'] = skips + [event['datetime']]
            validate_schedule(row)
            store(rows)
            return jsonify(skipped=event, next_event=next_event([row], holidays, now, calendar_events))

    @api.route('/api/v1/holidays')
    def holiday_day():
        return jsonify(holidays.get_day_type(request.args.get('date', taipei_now().date().isoformat())))

    @api.route('/api/v1/devices')
    def list_devices():
        return jsonify(devices=devices().list())

    @api.route('/api/v1/devices/<device_id>/commands', methods=['POST'])
    def device_command(device_id):
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != {'action'}:
            raise ValueError('Expected one command action')
        return jsonify(command=devices().command(device_id, data['action'])), 202

    return api
