"""Owner-scoped clips. Only a fixed, metadata-free PCM/WAVE encoding is stored."""
import base64
import json
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import re
import struct
from threading import BoundedSemaphore
import unicodedata
import uuid

from .storage import load_json, save_json

RATE = 16000
MAX_BYTES = 44 + 2 * RATE * 300
MAX_CLIPS = 8
MAX_LIBRARY_BYTES = 16 * 1024 * 1024
ID = re.compile(r'[0-9a-f]{32}')
# Bound simultaneous upload bodies in memory.
_upload_slots = BoundedSemaphore(2)
HEADER = struct.Struct('<4sI4s4sIHHIIHH4sI')


class RingtoneError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


@contextmanager
def upload_slot():
    if not _upload_slots.acquire(blocking=False):
        raise RingtoneError('ringtone_upload_busy', 429)
    try:
        yield
    finally:
        _upload_slots.release()


def validate_name(name):
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 60
            or any(unicodedata.category(char).startswith('C') for char in name)):
        raise RingtoneError('invalid_ringtone_name')
    return name.strip()


def validate_wave(raw):
    size = len(raw)
    if size > MAX_BYTES:
        raise RingtoneError('ringtone_too_large', 413)
    if (size <= HEADER.size or size % 2 or HEADER.unpack_from(raw) != (
            b'RIFF', size - 8, b'WAVE', b'fmt ', 16, 1, 1, RATE, RATE * 2, 2, 16, b'data', size - 44)):
        raise RingtoneError('invalid_wave', 415)


def validate_library(rows):
    if not isinstance(rows, dict) or len(rows) > MAX_CLIPS:
        raise RingtoneError('invalid_library')
    for key, row in rows.items():
        if (not isinstance(key, str) or not ID.fullmatch(key) or not isinstance(row, dict) or set(row) != {'name', 'wav'}
                or not isinstance(row['wav'], str) or len(row['wav']) > 4 * ((MAX_BYTES + 2) // 3)):
            raise RingtoneError('invalid_library')
        validate_name(row['name'])
        validate_wave(base64.b64decode(row['wav'], validate=True))


def library(directory):
    return load_json(Path(directory) / 'ringtones.json', {})


@lru_cache(maxsize=128)
def _catalog(path, file_stamp):
    # Files are atomically replaced. Cache names only, never private audio.
    return tuple((key, row['name']) for key, row in load_json(path, {}).items())


def catalog(directory):
    path = Path(directory) / 'ringtones.json'
    try:
        info = path.stat()
    except FileNotFoundError:
        return []
    return [dict(id=key, name=name) for key, name in
            _catalog(path, (info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size))]


def check_growth(state_root, growth):
    if growth <= 0:
        return
    # Keep room for other account data in the 20 MiB portable archive.
    root = Path(state_root)
    files = [root / 'ringtones.json', *(root / 'owners').glob('*/ringtones.json')]
    used = sum(path.stat().st_size for path in files if path.is_file())
    if used + growth > MAX_LIBRARY_BYTES:
        raise RingtoneError('ringtone_storage_full', 409)


def rename(directory, key, name, state_root):
    rows = library(directory)
    if key not in rows:
        raise RingtoneError('ringtone_not_found', 404)

    def stored_size(label):
        return len(json.dumps(label, ensure_ascii=False).encode('utf-8'))

    check_growth(state_root, stored_size(name) - stored_size(rows[key]['name']))
    rows[key]['name'] = name
    save_json(Path(directory) / 'ringtones.json', rows)
    return dict(id=key, name=name)


def add(directory, name, raw, state_root):
    encoded = base64.b64encode(raw).decode('ascii')
    check_growth(state_root, len(encoded) + 1024)
    rows = library(directory)
    if len(rows) >= MAX_CLIPS:
        raise RingtoneError('ringtone_quota', 409)
    key = uuid.uuid4().hex
    rows[key] = dict(name=name, wav=encoded)
    save_json(Path(directory) / 'ringtones.json', rows)
    return dict(id=key, name=name)


def audio(directory, key):
    row = library(directory).get(key)
    if row is None:
        raise RingtoneError('ringtone_not_found', 404)
    raw = base64.b64decode(row['wav'], validate=True)
    validate_wave(raw)
    return raw
