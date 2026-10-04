"""Host checks; uses the server's public holiday data, never its private state."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from webclock.services.holiday_service import HolidayService
from webclock.services.schedule_service import validate_schedule
from webclock.services.storage import revision

parser = argparse.ArgumentParser()
parser.add_argument("--arduinojson", type=Path, help="Directory containing ArduinoJson.h (7.4.3)")
args = parser.parse_args()
include = args.arduinojson
if include is None:
    headers = [path for path in (ROOT / ".esphome" / "build" / "webclock-alarm").rglob("ArduinoJson.h")
               if (path.parent / "ArduinoJson.hpp").is_file()]
    if not headers:
        parser.error("Compile the ESPHome YAML once to fetch ArduinoJson, or pass --arduinojson PATH")
    include = headers[0].parent
compiler = shutil.which("clang++") or shutil.which("g++")
if not compiler:
    parser.error("Install a C++17 host compiler (clang++ or g++)")

schedules = [validate_schedule(dict(id="wake", name="起床", time="07:30", rule={"weekdays": [1, 2, 3, 4, 5]}, skip_holidays=True))]
holidays = HolidayService().export()
config = dict(schema_version=2, timezone="Asia/Taipei")
config.update(config_revision=revision(config), schedule_revision=revision(schedules), holiday_revision=revision(holidays))
bundle = dict(config=config, schedules=dict(revision=revision(schedules), schedules=schedules), holidays=dict(holidays, revision=revision(holidays)))
with tempfile.TemporaryDirectory(prefix="webclock-firmware-test-") as folder:
    temp = Path(folder)
    fixture = temp / "fixture.json"
    fixture.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    for name in ("test_alarm_core", "test_sync_codec"):
        binary = temp / name
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                        "-I", str(ROOT / "components" / "webclock"), "-I", str(include),
                        str(ROOT / "tests" / (name + ".cpp")), "-o", str(binary)], check=True)
        subprocess.run([str(binary), str(fixture)] if name == "test_sync_codec" else [str(binary)], check=True)
print("PASS: alarm engine and schema-2 codec; physical hardware not tested")
