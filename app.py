from flask import Flask, render_template, jsonify, request, redirect, url_for
from datetime import datetime, timezone, timedelta
import holidays
import requests
from icalendar import Calendar
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

ICAL_URL = os.getenv('ICAL_URL', "")
NOTES_FILE = "manual_notes.json"
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

display_settings = {
    'mode': 'normal',
    'brightness': 100,
    'timezone_offset': 8,
    'language': DEFAULT_LANGUAGE,
}


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


def save_note(text, due_date):
    notes = load_notes()
    new_id = 1 if not notes else max(n['id'] for n in notes) + 1
    notes.append({'id': new_id, 'text': text, 'due_date': due_date})
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
def admin():
    return render_template(
        'admin.html',
        notes=load_notes(),
        settings=display_settings,
        **template_context()
    )


@app.route('/api/control', methods=['POST'])
def control():
    data = request.json or {}
    if 'mode' in data:
        display_settings['mode'] = data['mode']
    if 'brightness' in data:
        display_settings['brightness'] = int(data['brightness'])
    if 'timezone_offset' in data:
        display_settings['timezone_offset'] = int(data['timezone_offset'])
    if 'language' in data and data['language'] in SUPPORTED_LANGUAGES:
        display_settings['language'] = data['language']

    return jsonify({'status': 'ok', 'settings': display_settings})


@app.route('/add', methods=['POST'])
def add():
    text = request.form.get('note_text')
    date_part = request.form.get('note_date')
    time_part = request.form.get('note_time')
    full_time_str = ""
    if date_part:
        full_time_str = date_part
        if time_part:
            full_time_str += f" {time_part}"
    if text:
        save_note(text, full_time_str)
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

        if not due_date:
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
