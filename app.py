from flask import Flask, render_template, jsonify, request, redirect, url_for, abort
from datetime import datetime, timezone, timedelta
import holidays
import requests
from icalendar import Calendar
import json
import os
import time
import tempfile
from threading import Lock
from dotenv import load_dotenv

load_dotenv()

ICAL_URL = os.getenv('ICAL_URL', "")
NOTES_FILE = "manual_notes.json"
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webclock_state', 'settings.json')
CACHE_DURATION = 9000
DEFAULT_LANGUAGE = 'zh-TW'

SUPPORTED_LANGUAGES = {
    'zh-TW': '繁體中文',
    'zh-CN': '简体中文',
    'en': 'English',
    'ja': '日本語',
}

UI_TRANSLATIONS = {
    'zh-TW': {
        'app_title': 'Web Clock',
        'loading': '載入中...',
        'weekdays': ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'],
        'notice_close': '關閉',
        'page_error': '頁面發生錯誤，已改用可用資料繼續顯示',
        'standard_time_unavailable': '無法連線標準時間，暫用裝置時間',
        'status_parse_failed': '狀態資料解析失敗，時鐘繼續顯示',
        'server_unavailable': '無法連線本機伺服器，時鐘繼續顯示',
        'server_timeout': '本機伺服器回應逾時，時鐘繼續顯示',
        'admin_title': '時鐘後台',
        'display_control': '顯示控制',
        'normal_display': '正常顯示',
        'black_screen': '黑畫面',
        'brightness': '亮度',
        'dark': '暗',
        'bright': '亮',
        'timezone': '時區',
        'language': '語言',
        'manual_events': '手動提醒 / 事項',
        'event_text': '內容',
        'event_placeholder': '例如：倒垃圾、吃藥、會議',
        'date_optional': '日期（選填）',
        'time_optional': '時間（選填）',
        'display_window': '顯示時間區間（選填）',
        'display_mode': '區間模式',
        'range_mode': '指定日期時間',
        'daily_mode': '每天固定時段',
        'display_start': '開始顯示',
        'display_end': '結束顯示',
        'edit_window': '設定顯示區間',
        'save': '儲存',
        'settings_save_error': '設定未能儲存，將重新載入目前設定。',
        'window_error': '請填寫有效且完整的開始與結束時間。指定日期時，結束須晚於開始；每天時段不可相同，可跨午夜。兩欄皆空白可取消區間。',
        'add': '新增',
        'current_list': '目前列表',
        'delete': '刪除',
        'no_notes': '目前沒有事項',
    },
    'zh-CN': {
        'app_title': 'Web Clock',
        'loading': '加载中...',
        'weekdays': ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'],
        'notice_close': '关闭',
        'page_error': '页面发生错误，已改用可用数据继续显示',
        'standard_time_unavailable': '无法连接标准时间，暂用设备时间',
        'status_parse_failed': '状态数据解析失败，时钟继续显示',
        'server_unavailable': '无法连接本机服务器，时钟继续显示',
        'server_timeout': '本机服务器响应超时，时钟继续显示',
        'admin_title': '时钟后台',
        'display_control': '显示控制',
        'normal_display': '正常显示',
        'black_screen': '黑屏',
        'brightness': '亮度',
        'dark': '暗',
        'bright': '亮',
        'timezone': '时区',
        'language': '语言',
        'manual_events': '手动提醒 / 事项',
        'event_text': '内容',
        'event_placeholder': '例如：倒垃圾、吃药、会议',
        'date_optional': '日期（选填）',
        'time_optional': '时间（选填）',
        'display_window': '显示时间区间（选填）',
        'display_mode': '区间模式',
        'range_mode': '指定日期时间',
        'daily_mode': '每天固定时段',
        'display_start': '开始显示',
        'display_end': '结束显示',
        'edit_window': '设置显示区间',
        'save': '保存',
        'settings_save_error': '设置未能保存，将重新加载当前设置。',
        'window_error': '请填写有效且完整的开始与结束时间。指定日期时，结束须晚于开始；每天时段不可相同，可跨午夜。两栏皆空白可取消区间。',
        'add': '新增',
        'current_list': '当前列表',
        'delete': '删除',
        'no_notes': '当前没有事项',
    },
    'en': {
        'app_title': 'Web Clock',
        'loading': 'Loading...',
        'weekdays': ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
        'notice_close': 'Close',
        'page_error': 'The page hit an error and will keep showing available data.',
        'standard_time_unavailable': 'Could not reach standard time. Using device time for now.',
        'status_parse_failed': 'Could not read status data. The clock will keep running.',
        'server_unavailable': 'Could not reach the local server. The clock will keep running.',
        'server_timeout': 'The local server timed out. The clock will keep running.',
        'admin_title': 'Clock Admin',
        'display_control': 'Display Control',
        'normal_display': 'Normal Display',
        'black_screen': 'Black Screen',
        'brightness': 'Brightness',
        'dark': 'Dark',
        'bright': 'Bright',
        'timezone': 'Time Zone',
        'language': 'Language',
        'manual_events': 'Manual Reminders / Events',
        'event_text': 'Text',
        'event_placeholder': 'Example: take out trash, medicine, meeting',
        'date_optional': 'Date (optional)',
        'time_optional': 'Time (optional)',
        'display_window': 'Display window (optional)',
        'display_mode': 'Window mode',
        'range_mode': 'Specific dates and times',
        'daily_mode': 'Daily time window',
        'display_start': 'Display from',
        'display_end': 'Display until',
        'edit_window': 'Set display window',
        'save': 'Save',
        'settings_save_error': 'Settings could not be saved. Reloading current settings.',
        'window_error': 'Enter valid start and end values. For specific dates, end must follow start. Daily times must differ and may cross midnight. Leave both blank to remove the window.',
        'add': 'Add',
        'current_list': 'Current List',
        'delete': 'Delete',
        'no_notes': 'No items yet',
    },
    'ja': {
        'app_title': 'Web Clock',
        'loading': '読み込み中...',
        'weekdays': ['日曜日', '月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日'],
        'notice_close': '閉じる',
        'page_error': 'ページでエラーが発生しました。利用可能なデータで表示を続けます。',
        'standard_time_unavailable': '標準時刻に接続できません。端末の時刻を使用します。',
        'status_parse_failed': '状態データを読み取れません。時計表示を続けます。',
        'server_unavailable': 'ローカルサーバーに接続できません。時計表示を続けます。',
        'server_timeout': 'ローカルサーバーの応答がタイムアウトしました。時計表示を続けます。',
        'admin_title': '時計管理',
        'display_control': '表示設定',
        'normal_display': '通常表示',
        'black_screen': '黒画面',
        'brightness': '明るさ',
        'dark': '暗い',
        'bright': '明るい',
        'timezone': 'タイムゾーン',
        'language': '言語',
        'manual_events': '手動リマインダー / 予定',
        'event_text': '内容',
        'event_placeholder': '例：ごみ出し、薬、会議',
        'date_optional': '日付（任意）',
        'time_optional': '時刻（任意）',
        'display_window': '表示期間（任意）',
        'display_mode': '期間モード',
        'range_mode': '日時を指定',
        'daily_mode': '毎日の時間帯',
        'display_start': '表示開始',
        'display_end': '表示終了',
        'edit_window': '表示期間を設定',
        'save': '保存',
        'settings_save_error': '設定を保存できませんでした。現在の設定を再読み込みします。',
        'window_error': '有効な開始と終了を入力してください。日時指定では終了を開始より後に、毎日の時間帯では異なる時刻にしてください（日付をまたげます）。両方空欄で解除します。',
        'add': '追加',
        'current_list': '現在のリスト',
        'delete': '削除',
        'no_notes': '項目はありません',
    },
}

app = Flask(__name__)
tw_holidays = holidays.TW()
cached_google_events = []
last_google_fetch_time = 0
last_google_fetch_date = None


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

DEFAULT_SETTINGS = {
    'mode': 'normal',
    'brightness': 100,
    'timezone_offset': 8,
    'language': DEFAULT_LANGUAGE,
}
settings_lock = Lock()


def validate_settings(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULT_SETTINGS):
        raise ValueError('Invalid settings object')
    result = dict(data)
    for key, low, high in (('brightness', 0, 100), ('timezone_offset', -12, 14)):
        if key in result:
            value = result[key]
            if type(value) not in (int, str):
                raise ValueError('Invalid ' + key)
            result[key] = int(value)
            if not low <= result[key] <= high:
                raise ValueError('Invalid ' + key)
    if 'mode' in result and result['mode'] not in ('normal', 'black'):
        raise ValueError('Invalid display mode')
    if 'language' in result and result['language'] not in SUPPORTED_LANGUAGES:
        raise ValueError('Invalid language')
    return result


def load_display_settings():
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            saved = validate_settings(json.load(f))
    except FileNotFoundError:
        saved = {}
    return dict(DEFAULT_SETTINGS, **saved)


def save_display_settings(settings):
    directory = os.path.dirname(SETTINGS_FILE)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.settings-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, SETTINGS_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


display_settings = load_display_settings()


def get_local_now():
    offset = display_settings.get('timezone_offset', 8)
    tz = timezone(timedelta(hours=offset))
    return datetime.now(tz)


def load_notes():
    if not os.path.exists(NOTES_FILE):
        return []
    try:
        with open(NOTES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for note in data:
            if 'due_date' not in note:
                note['due_date'] = ""
        data.sort(key=lambda x: x['due_date'] if x['due_date'] else "9999")
        return data
    except Exception:
        return []


def parse_display_window(values):
    mode = values.get('display_mode', 'range')
    if mode not in ('range', 'daily'):
        raise ValueError('Invalid display mode')
    start = values.get('display_start', '')
    end = values.get('display_end', '')
    if not start and not end:
        return '', ''
    for value in (start, end):
        parsed = datetime.strptime(value, '%H:%M' if mode == 'daily' else '%Y-%m-%dT%H:%M')
        normalized = parsed.strftime('%H:%M') if mode == 'daily' else parsed.isoformat(timespec='minutes')
        if normalized != value:
            raise ValueError('Invalid display datetime')
    if end == start or (mode == 'range' and end < start):
        raise ValueError('Invalid display window order')
    return start, end


def save_note(text, due_date, display_start='', display_end='', display_mode='range'):
    notes = load_notes()
    new_id = 1 if not notes else max(n['id'] for n in notes) + 1
    notes.append({'id': new_id, 'text': text, 'due_date': due_date,
                  'display_start': display_start, 'display_end': display_end,
                  'display_mode': display_mode})
    with open(NOTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(notes, f, ensure_ascii=False)


def delete_note(note_id):
    notes = [n for n in load_notes() if n['id'] != int(note_id)]
    with open(NOTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(notes, f, ensure_ascii=False)


def get_calendar_events():
    global cached_google_events, last_google_fetch_time, last_google_fetch_date

    local_now = get_local_now()
    current_time = time.time()
    current_date = local_now.date()
    same_day = last_google_fetch_date == current_date
    not_expired = current_time - last_google_fetch_time < CACHE_DURATION

    if not_expired and same_day and (cached_google_events or last_google_fetch_time > 0):
        return cached_google_events

    events = []
    try:
        if "http" not in ICAL_URL:
            return []

        response = requests.get(ICAL_URL, timeout=10)
        cal = Calendar.from_ical(response.content)
        today = current_date

        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            summary = str(component.get('summary'))
            dtstart = component.get('dtstart').dt
            is_today = False
            time_display = ""

            if isinstance(dtstart, datetime):
                check_date = dtstart
                if dtstart.tzinfo is not None:
                    check_date = dtstart.astimezone(local_now.tzinfo)
                if check_date.date() == today:
                    is_today = True
                    time_display = check_date.strftime('%H:%M')
            elif dtstart == today:
                is_today = True

            if is_today:
                events.append({'text': summary, 'time': time_display})

        cached_google_events = events
        last_google_fetch_date = current_date
    except Exception as e:
        print(f"Google Calendar Error: {e}")

    last_google_fetch_time = current_time
    return cached_google_events


def template_context():
    language = display_settings.get('language', DEFAULT_LANGUAGE)
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    return {
        'language': language,
        'languages': SUPPORTED_LANGUAGES,
        'translations': UI_TRANSLATIONS,
    }


@app.route('/')
def index():
    return render_template('index.html', **template_context())


@app.route('/admin')
def admin(error=None, editing_id=None):
    return render_template(
        'admin.html',
        notes=load_notes(),
        settings=display_settings,
        error=error,
        editing_id=editing_id,
        **template_context()
    )


@app.route('/api/control', methods=['POST'])
def control():
    try:
        changes = validate_settings(request.get_json())
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid settings'}), 400
    with settings_lock:
        updated = dict(display_settings, **changes)
        try:
            save_display_settings(updated)
        except OSError:
            app.logger.exception('Could not save display settings')
            return jsonify({'error': 'Could not save settings'}), 500
        display_settings.update(updated)
        return jsonify({'status': 'ok', 'settings': display_settings})


@app.route('/add', methods=['POST'])
def add():
    try:
        display_start, display_end = parse_display_window(request.form)
    except ValueError:
        return admin(error='window_error'), 400
    text = request.form.get('note_text')
    date_part = request.form.get('note_date')
    time_part = request.form.get('note_time')
    full_time_str = ""
    if date_part:
        full_time_str = date_part
        if time_part:
            full_time_str += f" {time_part}"
    if text:
        save_note(text, full_time_str, display_start, display_end, request.form.get('display_mode', 'range'))
    return redirect(url_for('admin'))


@app.route('/schedule/<int:id>', methods=['POST'])
def schedule(id):
    notes = load_notes()
    note = next((note for note in notes if note['id'] == id), None)
    if note is None:
        abort(404)
    try:
        start, end = parse_display_window(request.form)
    except ValueError:
        return admin(error='window_error', editing_id=id), 400
    note.update(display_start=start, display_end=end, display_mode=request.form.get('display_mode', 'range'))
    with open(NOTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(notes, f, ensure_ascii=False)
    return redirect(url_for('admin'))


@app.route('/delete/<int:id>')
def delete(id):
    delete_note(id)
    return redirect(url_for('admin'))


@app.route('/api/status')
def status():
    now = get_local_now()
    today_str = now.strftime('%Y-%m-%d')
    server_timestamp = int(now.timestamp() * 1000)
    is_weekend = now.weekday() >= 5
    is_holiday = now.date() in tw_holidays or is_weekend

    manual_events = []
    for note in load_notes():
        due_date = note.get('due_date', '')
        should_show = False
        time_display = ""

        if note.get('display_start') or note.get('display_end'):
            try:
                start, end = parse_display_window(note)
            except (ValueError, TypeError):
                continue
            # Stored wall times follow the clock's configured timezone.
            if note.get('display_mode') == 'daily':
                current_time = now.strftime('%H:%M')
                if start < end:
                    should_show = start <= current_time < end
                else:
                    should_show = current_time >= start or current_time < end
            else:
                should_show = start <= now.isoformat(timespec='minutes')[:16] < end
            time_display = due_date[11:] if len(due_date) > 10 else ''
        elif not due_date:
            should_show = True
        elif due_date.startswith(today_str):
            should_show = True
            if len(due_date) > 10:
                time_display = due_date[11:]

        if should_show:
            manual_events.append({'text': note['text'], 'time': time_display})

    all_events = get_calendar_events() + manual_events
    all_events.sort(key=lambda x: x['time'] if x['time'] else "99:99")

    return jsonify({
        'server_timestamp': server_timestamp,
        'is_holiday': is_holiday,
        'events': all_events,
        'settings': display_settings,
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    app.run(host=host, port=port)
