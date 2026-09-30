"""Single-process JSON storage; replace with SQLite before adding writer processes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

# ponytail: one process owns JSON writes; use SQLite for multiple server workers.
storage_lock = RLock()


def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)
    except FileNotFoundError:
        return copy.deepcopy(default)


def save_json(path, value):
    directory = Path(path).resolve().parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.settings-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()
