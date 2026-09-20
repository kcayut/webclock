from flask import Flask, render_template, jsonify, request, redirect, url_for, abort, send_from_directory
from datetime import datetime, timezone, timedelta
import holidays
import requests
from icalendar import Calendar
import json
import os
import time
import tempfile
from threading import RLock
from dotenv import load_dotenv

load_dotenv()

ICAL_URL = os.getenv('ICAL_URL', "")
NOTES_FILE = os.getenv('NOTES_FILE', 'manual_notes.json')
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
        'night_title': '自動夜間模式',
        'night_enabled': '啟用夜間排程',
        'night_start': '夜間開始',
        'night_end': '恢復日間',
        'night_brightness': '夜間亮度',
        'night_black': '夜間使用黑畫面',
        'night_hint': '依後台時區每日執行。日間恢復上方亮度；手動黑畫面優先。僅調整網頁顯示，不控制螢幕背光。',
        'repeat_days': '重複星期',
        'repeat_hint': '不勾選代表每天；跨午夜時段依開始的星期計算。',
        'edit_note': '編輯提醒',
        'pause': '暫停',
        'resume': '恢復',
        'paused': '已暫停',
        'backup_title': '備份與還原',
        'backup_export': '下載備份',
        'backup_file': '選擇備份檔案',
        'backup_import': '匯入並取代',
        'backup_hint': '包含伺服器顯示設定與手動提醒，不含私人行事曆網址或瀏覽器本機提醒。匯入會取代現有資料。',
        'backup_confirm': '確定以這份備份取代目前設定與提醒？',
        'backup_error': '匯入失敗，請檢查備份格式及伺服器狀態。',
        'backup_done': '已還原備份。',
        'saved': '已儲存。',
        'countdown': '距離 {text} 還有 {minutes} 分鐘',
        'offline_ready': '已可離線開啟',
        'offline_unavailable': '離線開啟需要支援的瀏覽器與 HTTPS（或 localhost）',
        'offline_failed': '尚未完成離線準備，請連線後重試',
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
        'daily_mode': '每週／每日時段',
        'display_start': '開始顯示',
        'display_end': '結束顯示',
        'edit_window': '設定顯示區間',
        'save': '儲存',
        'settings_save_error': '設定未能儲存，將重新載入目前設定。',
        'window_error': '請檢查提醒內容、日期與時段。開始和結束須完整且不同；指定日期時結束須較晚。只填提醒時間時，也請選擇日期。',
        'add': '新增',
        'current_list': '目前列表',
        'delete': '刪除',
        'no_notes': '目前沒有事項',
    },
    'zh-CN': {
        'night_title': '自动夜间模式',
        'night_enabled': '启用夜间计划',
        'night_start': '夜间开始',
        'night_end': '恢复日间',
        'night_brightness': '夜间亮度',
        'night_black': '夜间使用黑屏',
        'night_hint': '按后台时区每天执行。日间恢复上方亮度；手动黑屏优先。仅调整网页显示，不控制屏幕背光。',
        'repeat_days': '重复星期',
        'repeat_hint': '不勾选代表每天；跨午夜时段按开始的星期计算。',
        'edit_note': '编辑提醒',
        'pause': '暂停',
        'resume': '恢复',
        'paused': '已暂停',
        'backup_title': '备份与恢复',
        'backup_export': '下载备份',
        'backup_file': '选择备份文件',
        'backup_import': '导入并替换',
        'backup_hint': '包含服务器显示设置与手动提醒，不含私人日历网址或浏览器本地提醒。导入会替换现有数据。',
        'backup_confirm': '确定用此备份替换当前设置与提醒？',
        'backup_error': '导入失败，请检查备份格式及服务器状态。',
        'backup_done': '已恢复备份。',
        'saved': '已保存。',
        'countdown': '距离 {text} 还有 {minutes} 分钟',
        'offline_ready': '已可离线打开',
        'offline_unavailable': '离线打开需要支持的浏览器与 HTTPS（或 localhost）',
        'offline_failed': '尚未完成离线准备，请联网后重试',
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
        'daily_mode': '每周／每天时段',
        'display_start': '开始显示',
        'display_end': '结束显示',
        'edit_window': '设置显示区间',
        'save': '保存',
        'settings_save_error': '设置未能保存，将重新加载当前设置。',
        'window_error': '请检查提醒内容、日期与时段。开始和结束须完整且不同；指定日期时结束须较晚。只填提醒时间时，也请选择日期。',
        'add': '新增',
        'current_list': '当前列表',
        'delete': '删除',
        'no_notes': '当前没有事项',
    },
    'en': {
        'night_title': 'Automatic night mode',
        'night_enabled': 'Enable night schedule',
        'night_start': 'Night begins',
        'night_end': 'Day resumes',
        'night_brightness': 'Night brightness',
        'night_black': 'Use a black screen at night',
        'night_hint': 'Runs daily in the admin timezone. Daytime restores the brightness above; manual black screen takes priority. Adjusts page appearance, not hardware backlight.',
        'repeat_days': 'Repeat on',
        'repeat_hint': 'Leave all unchecked for every day. Overnight windows belong to their starting weekday.',
        'edit_note': 'Edit reminder',
        'pause': 'Pause',
        'resume': 'Resume',
        'paused': 'Paused',
        'backup_title': 'Backup and restore',
        'backup_export': 'Download backup',
        'backup_file': 'Choose backup file',
        'backup_import': 'Import and replace',
        'backup_hint': 'Includes server display settings and manual reminders, excluding private calendar URLs and browser-local reminders. Import replaces current data.',
        'backup_confirm': 'Replace current settings and reminders with this backup?',
        'backup_error': 'Import failed. Check the backup format and server status.',
        'backup_done': 'Backup restored.',
        'saved': 'Saved.',
        'countdown': '{text} in {minutes} minutes',
        'offline_ready': 'Ready to open offline',
        'offline_unavailable': 'Offline opening requires a supported browser and HTTPS (or localhost)',
        'offline_failed': 'Offline setup incomplete. Reconnect and try again.',
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
        'daily_mode': 'Weekly / daily window',
        'display_start': 'Display from',
        'display_end': 'Display until',
        'edit_window': 'Set display window',
        'save': 'Save',
        'settings_save_error': 'Settings could not be saved. Reloading current settings.',
        'window_error': 'Check reminder text, dates and times. Both window times are required and must differ; dated windows must end after they start. A reminder time also needs a date.',
        'add': 'Add',
        'current_list': 'Current List',
        'delete': 'Delete',
        'no_notes': 'No items yet',
    },
    'ja': {
        'night_title': '自動ナイトモード',
        'night_enabled': '夜間スケジュールを有効にする',
        'night_start': '夜間の開始',
        'night_end': '昼間に戻す',
        'night_brightness': '夜間の明るさ',
        'night_black': '夜間は黒画面にする',
        'night_hint': '管理画面のタイムゾーンで毎日実行します。昼間は上の明るさに戻ります。手動の黒画面が優先されます。画面のバックライトは変更しません。',
        'repeat_days': '繰り返す曜日',
        'repeat_hint': '未選択は毎日です。日付をまたぐ時間帯は開始日の曜日に従います。',
        'edit_note': 'リマインダーを編集',
        'pause': '一時停止',
        'resume': '再開',
        'paused': '停止中',
        'backup_title': 'バックアップと復元',
        'backup_export': 'バックアップを保存',
        'backup_file': 'バックアップファイルを選択',
        'backup_import': '読み込んで置き換える',
        'backup_hint': 'サーバーの表示設定と手動リマインダーを含みます。非公開カレンダーURLとブラウザー内のリマインダーは含みません。読み込みで現在のデータを置き換えます。',
        'backup_confirm': 'このバックアップで現在の設定とリマインダーを置き換えますか？',
        'backup_error': '復元できませんでした。ファイル形式とサーバーの状態を確認してください。',
        'backup_done': '復元しました。',
        'saved': '保存しました。',
        'countdown': '{text} まであと {minutes} 分',
        'offline_ready': 'オフラインで開けます',
        'offline_unavailable': 'オフライン利用には対応ブラウザーと HTTPS（または localhost）が必要です',
        'offline_failed': 'オフラインの準備が未完了です。接続して再試行してください。',
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
        'daily_mode': '毎週・毎日の時間帯',
        'display_start': '表示開始',
        'display_end': '表示終了',
        'edit_window': '表示期間を設定',
        'save': '保存',
        'settings_save_error': '設定を保存できませんでした。現在の設定を再読み込みします。',
        'window_error': '内容、日付、時刻を確認してください。開始と終了は両方必要で、異なる時刻にしてください。日時指定では終了を開始より後にしてください。予定の時刻には日付も必要です。',
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

DEFAULT_NIGHT = {'enabled': False, 'start': '22:00', 'end': '07:00', 'brightness': 15, 'black': False}
DEFAULT_SETTINGS = {
    'mode': 'normal',
    'brightness': 100,
    'timezone_offset': 8,
    'language': DEFAULT_LANGUAGE,
}
# ponytail: single-process file storage; use a database before adding writer processes.
settings_lock = RLock()


def validate_settings(data):
    if not isinstance(data, dict) or set(data) - (set(DEFAULT_SETTINGS) | {'night'}):
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
    if 'night' in result:
        night = result['night']
        if not isinstance(night, dict) or set(night) != set(DEFAULT_NIGHT):
            raise ValueError('Invalid night settings')
        if type(night['enabled']) is not bool or type(night['black']) is not bool:
            raise ValueError('Invalid night switch')
        if type(night['brightness']) is not int or not 0 <= night['brightness'] <= 100:
            raise ValueError('Invalid night brightness')
        for key in ('start', 'end'):
            validate_time(night[key])
        if night['start'] == night['end']:
            raise ValueError('Night times must differ')
    return result


def validate_time(value):
    if not isinstance(value, str) or datetime.strptime(value, '%H:%M').strftime('%H:%M') != value:
        raise ValueError('Invalid time')
    return value


def load_display_settings():
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            saved = validate_settings(json.load(f))
    except FileNotFoundError:
        saved = {}
    return dict(DEFAULT_SETTINGS, **saved)


def save_display_settings(settings):
    save_json(SETTINGS_FILE, settings)


def save_json(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.settings-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def migrate_notes(legacy_path):
    # Docker's old single-file bind mount cannot be replaced atomically.
    # Copy it once into the already-persistent state directory; keep the original.
    if not os.path.exists(NOTES_FILE) and os.path.isfile(legacy_path):
        with open(legacy_path, encoding='utf-8') as f:
            content = f.read()
        data = json.loads(content) if content.strip() else []
        if not isinstance(data, list):
            raise ValueError('Invalid legacy reminders')
        save_json(NOTES_FILE, data)


if os.getenv('NOTES_FILE'):
    migrate_notes('manual_notes.json')

display_settings = load_display_settings()


def get_local_now():
    offset = display_settings.get('timezone_offset', 8)
    tz = timezone(timedelta(hours=offset))
    return datetime.now(tz)


def load_notes():
    with settings_lock:
        try:
            with open(NOTES_FILE, encoding='utf-8') as f:
                content = f.read()
                data = json.loads(content) if content.strip() else []
        except FileNotFoundError:
            return []
        for note in data:
            note.setdefault('due_date', '')
        return sorted(data, key=lambda note: note['due_date'] or '9999')


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


def save_note(text, due_date, display_start='', display_end='', display_mode='range', weekdays=None):
    with settings_lock:
        notes = load_notes()
        new_id = 1 if not notes else max(n['id'] for n in notes) + 1
        notes.append({'id': new_id, 'text': text, 'due_date': due_date,
                      'display_start': display_start, 'display_end': display_end,
                      'display_mode': display_mode, 'weekdays': weekdays or [], 'enabled': True})
        save_json(NOTES_FILE, notes)


def delete_note(note_id):
    with settings_lock:
        notes = [n for n in load_notes() if n['id'] != int(note_id)]
        save_json(NOTES_FILE, notes)


def validate_note(note):
    if not isinstance(note, dict) or set(note) - {
        'id', 'text', 'due_date', 'display_start', 'display_end', 'display_mode', 'weekdays', 'enabled'
    }:
        raise ValueError('Invalid reminder')
    if not isinstance(note.get('text'), str) or not 1 <= len(note['text'].strip()) <= 1000:
        raise ValueError('Invalid text')
    start, end = parse_display_window(note)
    due = note.get('due_date', '')
    if not isinstance(due, str):
        raise ValueError('Invalid date')
    if due:
        fmt = '%Y-%m-%d %H:%M' if len(due) > 10 else '%Y-%m-%d'
        if datetime.strptime(due, fmt).strftime(fmt) != due:
            raise ValueError('Invalid date')
    days = note.get('weekdays', [])
    if not isinstance(days, list) or len(days) > 7 or any(type(day) is not int or not 0 <= day <= 6 for day in days):
        raise ValueError('Invalid weekdays')
    if type(note.get('enabled', True)) is not bool:
        raise ValueError('Invalid enabled flag')
    return dict(note, text=note['text'].strip(), due_date=due, display_start=start, display_end=end,
                display_mode=note.get('display_mode', 'range'), weekdays=sorted(set(days)),
                enabled=note.get('enabled', True))


def note_from_form(existing=None):
    note = dict(existing or {})
    note.update(display_mode=request.form.get('display_mode', 'range'),
                display_start=request.form.get('display_start', ''),
                display_end=request.form.get('display_end', ''))
    if 'note_text' in request.form:
        date = request.form.get('note_date', '')
        clock_time = request.form.get('note_time', '')
        if clock_time and not date:
            raise ValueError('Time requires a date')
        note.update(text=request.form['note_text'], due_date=date + (' ' + clock_time if clock_time else ''))
    # Old clients editing only a window preserve an existing weekday selection.
    if 'weekdays_present' in request.form:
        note['weekdays'] = [int(day) for day in request.form.getlist('weekdays')]
    if note['display_mode'] != 'daily':
        note['weekdays'] = []
    return validate_note(note)


def note_visible(note, now):
    if not note.get('enabled', True):
        return False
    start, end = parse_display_window(note)
    if note.get('display_mode') == 'daily':
        clock_time = now.strftime('%H:%M')
        # An overnight window belongs to the day it starts, even after midnight.
        anchor = now - timedelta(days=1) if start and start > end and clock_time < end else now
        if note.get('weekdays') and anchor.weekday() not in note['weekdays']:
            return False
        return not start or (start <= clock_time < end if start < end else clock_time >= start or clock_time < end)
    if start:
        return start <= now.isoformat(timespec='minutes')[:16] < end
    return not note.get('due_date') or note['due_date'].startswith(now.strftime('%Y-%m-%d'))


def next_note_time(note, now):
    if not note.get('enabled', True):
        return None
    start, _ = parse_display_window(note)
    if note.get('display_mode') == 'daily':
        if not start:
            return None
        for offset in range(8):
            day = now + timedelta(days=offset)
            if note.get('weekdays') and day.weekday() not in note['weekdays']:
                continue
            candidate = datetime.strptime(day.strftime('%Y-%m-%d') + ' ' + start, '%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
            if candidate > now:
                return candidate
    else:
        due = note.get('due_date', '')
        value = due if len(due) > 10 else start.replace('T', ' ')
        if value:
            candidate = datetime.strptime(value, '%Y-%m-%d %H:%M').replace(tzinfo=now.tzinfo)
            if candidate > now and note_visible(note, candidate):
                return candidate
    return None


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
                events.append({'text': summary, 'time': time_display,
                               'starts_at': int(check_date.replace(tzinfo=local_now.tzinfo).timestamp() * 1000) if time_display else None})

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
        settings={'night': DEFAULT_NIGHT, **display_settings},
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
        note = note_from_form()
    except (ValueError, TypeError):
        return admin(error='window_error'), 400
    save_note(note['text'], note['due_date'], note['display_start'], note['display_end'],
              note['display_mode'], note['weekdays'])
    return redirect(url_for('admin'))


@app.route('/schedule/<int:id>', methods=['POST'])
def schedule(id):
    with settings_lock:
        notes = load_notes()
        note = next((note for note in notes if note['id'] == id), None)
        if note is None:
            abort(404)
        try:
            updated = note_from_form(note)
        except (ValueError, TypeError):
            return admin(error='window_error', editing_id=id), 400
        note.update(updated)
        save_json(NOTES_FILE, notes)
    return redirect(url_for('admin'))


@app.route('/toggle/<int:id>', methods=['POST'])
def toggle(id):
    with settings_lock:
        notes = load_notes()
        note = next((note for note in notes if note['id'] == id), None)
        if note is None:
            abort(404)
        note['enabled'] = not note.get('enabled', True)
        save_json(NOTES_FILE, notes)
    return redirect(url_for('admin'))


@app.route('/api/backup', methods=['GET', 'POST'])
def backup():
    if request.headers.get('Origin', request.host_url.rstrip('/')) != request.host_url.rstrip('/'):
        abort(403)
    with settings_lock:
        if request.method == 'GET':
            response = jsonify(version=1, settings=display_settings, notes=load_notes())
            response.headers['Content-Disposition'] = 'attachment; filename="webclock-backup.json"'
            response.headers['Cache-Control'] = 'no-store'
            return response
        if request.content_length is None or request.content_length > 1024 * 1024:
            return jsonify(error='Backup too large'), 413
        try:
            data = request.get_json()
            if not isinstance(data, dict) or set(data) != {'version', 'settings', 'notes'} or type(data['version']) is not int or data['version'] != 1:
                raise ValueError('Unknown backup format')
            settings = dict(DEFAULT_SETTINGS, **validate_settings(data['settings']))
            if not {'mode', 'brightness', 'timezone_offset', 'language'} <= set(data['settings']):
                raise ValueError('Incomplete settings')
            if not isinstance(data['notes'], list) or len(data['notes']) > 1000:
                raise ValueError('Invalid notes')
            notes = [validate_note(note) for note in data['notes']]
            ids = [note.get('id') for note in notes]
            if any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('Invalid reminder IDs')
        except (ValueError, TypeError, KeyError):
            return jsonify(error='Invalid backup'), 400
        previous_notes = load_notes()
        try:
            # Retain the previous data even if interrupted between the two file replacements.
            save_json(os.path.join(os.path.dirname(SETTINGS_FILE), 'before-import.json'),
                      dict(version=1, settings=display_settings, notes=previous_notes))
            save_json(NOTES_FILE, notes)
            try:
                save_display_settings(settings)
            except OSError:
                save_json(NOTES_FILE, previous_notes)
                raise
        except OSError:
            app.logger.exception('Backup restore failed; previous data retained in before-import.json')
            return jsonify(error='Could not restore backup'), 500
        display_settings.clear()
        display_settings.update(settings)
        return jsonify(status='ok')


@app.route('/sw.js')
def service_worker():
    response = send_from_directory(app.root_path, 'sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response


@app.route('/delete/<int:id>')
def delete(id):
    delete_note(id)
    return redirect(url_for('admin'))


@app.route('/api/status')
def status():
    now = get_local_now()
    server_timestamp = int(now.timestamp() * 1000)
    is_weekend = now.weekday() >= 5
    is_holiday = now.date() in tw_holidays or is_weekend

    manual_events = []
    upcoming = []
    for note in load_notes():
        try:
            if note_visible(note, now):
                due = note.get('due_date', '')
                manual_events.append({'text': note['text'], 'time': due[11:] if len(due) > 10 else ''})
            candidate = next_note_time(note, now)
            if candidate:
                upcoming.append({'text': note['text'], 'starts_at': int(candidate.timestamp() * 1000)})
        except (ValueError, TypeError):
            continue

    calendar_events = get_calendar_events()
    for event in calendar_events:
        if (event.get('starts_at') or 0) > server_timestamp:
            upcoming.append({'text': event['text'], 'starts_at': event['starts_at']})
    all_events = [{'text': event['text'], 'time': event['time']} for event in calendar_events] + manual_events
    all_events.sort(key=lambda event: event['time'] or '99:99')

    return jsonify({
        'server_timestamp': server_timestamp,
        'is_holiday': is_holiday,
        'events': all_events,
        'next_event': min(upcoming, key=lambda event: event['starts_at']) if upcoming else None,
        'settings': display_settings,
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    app.run(host=host, port=port)
