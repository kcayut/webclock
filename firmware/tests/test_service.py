"""Run the desk firmware's C++ sync logic against a temporary real WebClock service."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import app as clock
import test_control_api as control
import test_managed_display as managed


class DeskServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.binary = Path(tmp.name) / "desk-sync"
        includes = list((ROOT / "firmware/ee04-clock/.esphome/build").rglob("src/ArduinoJson.hpp"))
        if not includes:
            raise RuntimeError("Compile the ESPHome firmware first to obtain ArduinoJson")
        subprocess.run([shutil.which("clang++") or "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-I", str(includes[0].parent),
                        "-I", str(ROOT / "firmware/components/webclock"), str(HERE / "service_driver.cpp"),
                        "-o", str(cls.binary)], check=True)

    def firmware(self, data, transport=None):
        with subprocess.Popen([self.binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              encoding="utf-8") as proc:
            def send(value):
                proc.stdin.write(json.dumps(value) + "\n")
                proc.stdin.flush()
            try:
                send(data)
                for line in proc.stdout:
                    msg = json.loads(line)
                    if "method" not in msg:
                        self.assertEqual(proc.wait(timeout=10), 0)
                        return msg
                    send(transport(msg))
                self.fail("firmware exited before sending a result")
            finally:
                proc.stdin.close()

    def fixture(self, cls):
        api = cls()
        self.addCleanup(api.doCleanups)
        api.setUp()
        return api

    def test_alarm_round_trip_offline_conflict_and_delete(self):
        api = self.fixture(control.ControlApiTest)
        token = api.issue()["token"]
        admin_url = "/api/v1/schedules"
        def http(req):
            resp = api.call(token, req["method"], req["path"][1:], req["body"])
            return {"status": resp.status_code, "body": resp.json}
        def sync(state, transport=http, **changes):
            return self.firmware(dict(state, **changes), transport)
        def rows():
            return api.admin.get(admin_url).json["schedules"]

        state = sync({"value": 1440 + 450, "base": -1})
        self.assertTrue(state["ok"])
        resource = admin_url + "/" + state["id"]
        self.assertEqual([(r["time"], r["enabled"]) for r in rows()], [("07:30", True)])
        self.assertEqual(api.admin.put(resource, json={"time": "08:15", "enabled": False}).status_code, 200)
        state = sync(state, id="")  # reboot, replay original create without duplicating
        self.assertEqual((state["base"], state["value"], len(rows())), (495, 495, 1))
        state = sync(state, lambda req: {"body": {}, "status": 0}, value=1440 + 540)
        self.assertFalse(state["ok"])
        self.assertEqual((state["base"], state["value"]), (495, 1980))
        state = sync(state, while_waiting=1981)
        self.assertEqual((rows()[0]["time"], state["value"], state["base"]), ("09:00", 1981, 1980))
        state = sync(state)
        self.assertEqual(rows()[0]["time"], "09:01")
        def race(req):
            if req["method"] == "PATCH":
                api.admin.put(resource, json={"time": "10:16"})
            return http(req)
        state = sync(state, race, value=1500)
        self.assertFalse(state["ok"])  # CAS conflict preserves offline settings until next read
        state = sync(state)
        self.assertEqual(state["value"], 2056)
        unknown = sync(state, lambda req: {"status": 404, "body": {}})
        self.assertFalse(unknown["ok"])  # A proxy error cannot disable a local alarm.
        self.assertEqual(unknown["value"], state["value"])
        self.assertEqual(api.admin.delete(resource).status_code, 200)
        state = sync(state, id="")
        self.assertEqual((state["base"], state["value"], rows()), (-2, 616, []))
        state = sync(state, save_after=1440)
        self.assertEqual((state["base"], state["generation"]), (-1, 1))
        state = sync(state, id="")
        self.assertEqual((rows()[0]["time"], rows()[0]["enabled"]), ("00:00", True))
        api.admin.put(admin_url + "/" + state["id"], json={"rule": {"weekdays": [1]}})
        self.assertEqual(sync(state)["base"], -2)
        self.assertEqual(rows()[0]["rule"], {"weekdays": [1]})

    def test_daily_skip_resume_cancel_and_offline_expiry(self):
        api = self.fixture(control.ControlApiTest)
        token = api.issue()["token"]

        def http(req):
            resp = api.call(token, req["method"], req["path"][1:], req["body"])
            return {"status": resp.status_code, "body": resp.json}

        def sync(state, **changes):
            result = self.firmware(dict(state, **changes), http)
            self.assertTrue(result["ok"], result)
            return result

        value = 1440 + 450
        state = sync({"value": value, "base": -1})
        resource = "/api/v1/schedules/" + state["id"]
        def schedule():
            return api.call(token, "GET", "schedules/" + state["id"]).json["schedule"]

        web = api.admin.post(resource + "/skip-next", json={})
        self.assertEqual(web.status_code, 200, web.json)
        when = web.json["skipped"]["datetime"]
        target = int(datetime.fromisoformat(when).timestamp()) // 60
        now = target - 1
        state = sync(state, now=now)
        self.assertEqual((state["value"], state["skip"], state["base_skip"]), (value, target, target))

        # Restore on the desk while a previous poll is still in flight.
        yesterday = (datetime.fromisoformat(when) - timedelta(days=1)).isoformat()
        self.assertEqual(api.admin.put(resource, json={"skipped_occurrences": [yesterday, when]}).status_code, 200)
        state = sync(state, now=now, skip_while_waiting=0)
        self.assertEqual((state["skip"], state["base_skip"]), (0, target))
        state = sync(state, now=now)
        self.assertEqual(schedule()["skipped_occurrences"], [yesterday])

        # Skip on the desk, replay after reboot, then resume on the web.
        state = sync(state, now=now, skip=target)
        state = sync(state, now=now, id="")
        row = schedule()
        self.assertEqual((row["enabled"], row["skipped_occurrences"]), (True, [when]))
        self.assertEqual(api.admin.put(resource, json={"skipped_occurrences": []}).status_code, 200)
        state = sync(state, now=now)
        self.assertEqual((state["skip"], state["base_skip"]), (0, 0))

        # The web UI can retain today's skipped minute and already skip tomorrow.
        tomorrow = (datetime.fromisoformat(when) + timedelta(days=1)).isoformat()
        self.assertEqual(api.admin.put(resource, json={"skipped_occurrences": [when, tomorrow]}).status_code, 200)
        state = sync(state, now=target)
        self.assertEqual((state["last_minute"], state["skip"]), (target, target + 1440))
        self.assertEqual(api.admin.put(resource, json={"skipped_occurrences": []}).status_code, 200)
        state = sync(state, now=target + 1)

        # Reconnect after an offline skip: the following day remains enabled.
        state = sync(state, now=target + 1, skip=target)
        self.assertEqual((state["value"], state["skip"]), (value, 0))
        state = sync(state, now=target + 1, skip=target + 1440)
        state = sync(state, now=target + 1, value=450, skip=0)
        row = schedule()
        self.assertEqual((row["enabled"], row["time"], row["skipped_occurrences"]), (False, "07:30", []))

    def test_ticker_on_public_display(self):
        api = self.fixture(control.ControlApiTest)
        now = datetime.fromisoformat("2026-10-05T08:00:00+08:00")
        events = [{"text": "晨間會議", "time": "08:30", "all_day": False,
                   "starts_at": int((now + timedelta(minutes=30)).timestamp() * 1000)},
                  {"text": "紀念日", "time": "", "all_day": True, "starts_at": int(now.timestamp() * 1000)}]
        clock.save_json(api.root / "notes.json", [dict(id=1, text="繳費", due_date="2026-10-05 09:00")])
        with patch.object(clock, "calendar_display_events", return_value=events), patch.object(clock, "get_local_now", return_value=now):
            payload = api.program.get("/api/status", headers={"X-WebClock-Event-Kinds": "1"}).json
            legacy = api.program.get("/api/status").json
        data = self.firmware({"display": payload})
        combined = "08:30 晨間會議 / 09:00 繳費 / 紀念日"
        self.assertEqual(data, dict(ttl=60000, line=combined, reminders="09:00 繳費",
                                    calendar="08:30 晨間會議 / 紀念日", disabled=""))
        self.assertEqual(self.firmware({"display": legacy}),
                         dict(ttl=60000, line=combined, reminders="", calendar="", disabled=""))
        self.assertEqual(self.firmware({"display": payload, "scoped": True})["line"], "")

    def test_ticker_byte_limit_and_replacement(self):
        texts = ["a" * 2048, "b" * 2048, "c" * 2048, "d" * 2039]
        events = [dict(kind=kind, text=value) for kind, value in zip(("reminder", "calendar") * 2, texts)]
        payload = {"events": events + [dict(kind="calendar", text="trailing")]}
        data = self.firmware({"display": payload})
        self.assertEqual(len(data["line"].encode()), 8192)
        self.assertEqual(data["line"], " / ".join(texts))
        self.assertEqual(data["calendar"], " / ".join(texts[1::2] + ["trailing"]))
        self.assertEqual(data["reminders"], " / ".join(texts[::2]))

        prefix = "a" * 2047
        changed = {"events": [dict(kind="calendar", text=prefix + "界")]}
        self.assertEqual(self.firmware({"display": changed, "previous_display": payload}),
                         dict(ttl=60000, line=prefix, reminders="", calendar=prefix, disabled=""))

    def test_ticker_reminders_survive_calendar_filling_combined_view(self):
        calendar = ["a" * 2048, "b" * 2048, "c" * 2048, "d" * 2039]
        events = [dict(kind="calendar", text=value) for value in calendar]
        events += [dict(kind="reminder", text="繳費"), dict(kind="calendar", text="溢出的行事曆項目"),
                   dict(kind="reminder", text="充電")]
        data = self.firmware({"display": {"events": events}})
        self.assertEqual(data["line"], " / ".join(calendar))
        self.assertEqual(data["calendar"], data["line"])
        self.assertEqual(data["reminders"], "繳費 / 充電")

    def test_ticker_on_paired_display(self):
        server = self.fixture(managed.ManagedDisplayTest)
        group = server.group("Desk", content={"calendar_source_ids": ["a"]})
        _, identity = server.device(group)
        paired = clock.app.test_client()
        invite = server.service().create_invite(server.owner, group["id"])
        native = {"X-WebClock-Client": "native-v1"}
        attempt = paired.post("/api/v2/device/token/prepare", base_url="https://localhost",
                              json={}, headers=native).json
        native["Authorization"] = "Bearer " + attempt["token"]
        joined = paired.post("/api/v2/device/token/join", base_url="https://localhost", headers=native,
                             json={"attempt_id": attempt["attempt_id"], "code": invite["code"]})
        self.assertEqual(joined.status_code, 201, joined.json)
        clock.save_json(server.root / "manual_notes.json", [
            dict(id=1, text="只給桌鐘群組", due_date="", targets={"group_ids": [group["id"]], "device_ids": []}),
            dict(id=2, text="別台的內容", due_date="", targets={"group_ids": [], "device_ids": [identity["device_id"]]}),
        ])
        headers = {"Authorization": "Bearer " + attempt["token"], "X-WebClock-Event-Kinds": "1"}
        event = dict(source_id="a", uid="desk-calendar", text="群組行事曆", all_day=True,
                     starts_at=int(server.instant.timestamp() * 1000))
        events = [event, dict(event, source_id="b", text="別組行事曆")]
        with patch.object(clock, "get_calendar_events", return_value=events):
            response = paired.get("/api/v2/device/display", base_url="https://localhost", headers=headers)
        self.assertEqual(response.status_code, 200, response.json)
        payload = response.json
        self.assertEqual(self.firmware({"display": payload, "scoped": True}),
                         dict(ttl=60000, line="群組行事曆 / 只給桌鐘群組", reminders="只給桌鐘群組",
                              calendar="群組行事曆", disabled=""))
        stamp = payload["server_timestamp"]
        short = dict(payload, lease=dict(issued_at=stamp, expires_at=stamp + 500))
        self.assertEqual(self.firmware({"display": short, "scoped": True})["ttl"], 500)
        empty = dict(ttl=0, line="", reminders="", calendar="", disabled="")
        expired = dict(payload, lease=dict(issued_at=stamp, expires_at=stamp))
        self.assertEqual(self.firmware({"display": expired, "previous_display": payload, "scoped": True}), empty)
        server.service().revoke(server.owner, joined.json["identity"]["device_id"])
        response = paired.get("/api/v2/device/display", base_url="https://localhost", headers=headers)
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.firmware({"display": response.json, "previous_display": payload, "scoped": True}), empty)


if __name__ == "__main__":
    unittest.main()
