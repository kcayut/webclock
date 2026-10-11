"""WebClock's product version, shared by source and packaged installations."""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent.parent / 'VERSION').read_text().strip()
except FileNotFoundError:
    __version__ = 'unknown'
