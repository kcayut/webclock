"""Run the desk firmware's C++ sync logic against a temporary real WebClock service."""
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

    def test_ticker_on_public_display(self):
        api = self.fixture(control.ControlApiTest)
        events = [{"text": "晨間會議", "time": "08:30", "all_day": False, "starts_at": 1795305600000},
                  {"text": "紀念日", "time": "", "all_day": True, "starts_at": 1795305600000}]
        with patch.object(clock, "calendar_display_events", return_value=events):
            payload = api.program.get("/api/status").json
        data = self.firmware({"display": payload})
        self.assertEqual(data, {"ttl": 60000, "line": "08:30 晨間會議 / 紀念日"})
        self.assertEqual(self.firmware({"display": payload, "scoped": True})["line"], "")

    def test_ticker_on_paired_display(self):
        server = self.fixture(managed.ManagedDisplayTest)
        group = server.group("Desk")
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
        response = paired.get("/api/v2/device/display", base_url="https://localhost",
                              headers={"Authorization": "Bearer " + attempt["token"]})
        self.assertEqual(response.status_code, 200, response.json)
        payload = response.json
        self.assertEqual(self.firmware({"display": payload, "scoped": True}),
                         {"ttl": 60000, "line": "只給桌鐘群組"})
        payload["lease"]["expires_at"] = payload["server_timestamp"] + 500
        self.assertEqual(self.firmware({"display": payload, "scoped": True})["ttl"], 500)
        payload["lease"]["expires_at"] -= 500
        self.assertEqual(self.firmware({"display": payload, "scoped": True}), {"ttl": 0, "line": ""})


if __name__ == "__main__":
    unittest.main()
