"""Central device management: python3 -m unittest discover -s tests -p test_device_service.py."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webclock.services.device_service import DeviceService, REPORT_FIELDS
from webclock.services.storage import load_json, save_json


class DeviceServiceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "devices.json"
        self.service = DeviceService(self.path)
        self.service.register({"id": "bedroom", "name": "Bedroom"})

    def test_registration_minimal_report_and_restart_persistence(self):
        self.assertFalse(self.service.list()[0]["online"])
        response = self.service.report({"id": "bedroom"})
        self.assertTrue(response["device"]["online"])
        self.assertEqual(response["commands"], [])
        self.assertEqual(set(response["device"]),
                         {"id", "name", "registered_at", "last_seen", "online", "commands"})
        renamed = self.service.register({"id": "bedroom", "name": " New name "})
        self.assertEqual(renamed["name"], "New name")
        self.assertEqual(renamed["last_seen"], response["device"]["last_seen"])
        self.assertEqual(DeviceService(self.path).list(), [renamed])

    def test_optional_reports_preserve_unspecified_values_and_validate_inputs(self):
        values = {field: " value " for field in REPORT_FIELDS}
        self.service.report({"id": "bedroom", **values})
        result = self.service.report({"id": "bedroom"})["device"]
        for field in values:
            self.assertEqual(result[field], "value")
        previous = self.path.read_bytes()
        invalid_reports = [{"id": "bedroom", field: value}
                           for field in REPORT_FIELDS for value in (None, True, [], "", " ", "x" * 129)]
        invalid_reports += [{"id": "bedroom", field: None}
                            for field in ("sound_revision", "rtc_ok", "wifi_rssi", "power", "battery", "extra")]
        invalid_reports.extend([[], {}, {"id": "../device"}])
        invalid_reports.extend({"id": "bedroom", "acknowledged_commands": value}
                               for value in (None, "command", ["bad/id"], [True], ["id"] * 101))
        for report in invalid_reports:
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.service.report(report)
            self.assertEqual(self.path.read_bytes(), previous)
        with self.assertRaises(KeyError):
            self.service.report({"id": "unknown"})

    def test_sync_is_idempotent_and_acknowledgements_only_affect_own_device(self):
        self.service.register({"id": "office", "name": "Office"})
        command = self.service.command("bedroom", "sync")
        other = self.service.command("office", "sync")
        self.assertEqual(self.service.command("bedroom", "sync"), command)
        self.assertEqual(self.service.report({"id": "bedroom"})["commands"], [command])
        report = {"id": "bedroom", "acknowledged_commands": [other["id"], "unknown"]}
        self.assertEqual(self.service.report(report)["commands"], [command])
        report["acknowledged_commands"] = [command["id"], other["id"]]
        self.assertEqual(self.service.report(report)["commands"], [])
        self.assertEqual(DeviceService(self.path).report({"id": "office"})["commands"], [other])
        self.assertNotEqual(self.service.command("bedroom", "sync")["id"], command["id"])
        for action in ("restart", "test_sound", "unknown", None, []):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.service.command("bedroom", action)
        with self.assertRaises(KeyError):
            self.service.command("unknown", "sync")

    def test_legacy_fields_and_commands_are_retained_but_not_exposed(self):
        stored = load_json(self.path, {})
        legacy_fields = {"sound_revision": "old", "rtc_ok": True, "wifi_rssi": -50,
                         "power": "usb", "battery": 90, "extra": {"keep": True}}
        legacy_commands = [{"id": "sound", "action": "test_sound"},
                           {"id": "restart", "action": "restart"}]
        sync = {"id": "sync", "action": "sync", "created_at": "2026-09-30T00:00:00+00:00"}
        stored["bedroom"].update(legacy_fields, commands=legacy_commands + [{**sync, "private": "old"}])
        save_json(self.path, stored)
        self.assertEqual(self.service.command("bedroom", "sync"), sync)
        reports = [self.service.list()[0], self.service.register({"id": "bedroom", "name": "Bedroom"}),
                   self.service.report({"id": "bedroom"})["device"]]
        for device in reports:
            self.assertFalse(set(device) & set(legacy_fields))
            self.assertEqual(device["commands"], [sync])
        response = self.service.report({"id": "bedroom", "acknowledged_commands": ["sync", "sound", "restart"]})
        self.assertEqual(response["commands"], [])
        after = load_json(self.path, {})["bedroom"]
        self.assertEqual(after["commands"], legacy_commands)
        for key, value in legacy_fields.items():
            self.assertEqual(after[key], value)

    def test_registration_limit_and_validation_do_not_drop_devices(self):
        record = load_json(self.path, {})["bedroom"]
        save_json(self.path, {f"device{index}": {**record, "id": f"device{index}"} for index in range(100)})
        self.service.register({"id": "device0", "name": "Renamed"})
        previous = self.path.read_bytes()
        for registration in ({"id": "extra", "name": "Extra"}, [], {},
                             {"id": "device0", "name": ""}, {"id": "device0", "name": "Name", "extra": True}):
            with self.subTest(registration=registration), self.assertRaises(ValueError):
                self.service.register(registration)
            self.assertEqual(self.path.read_bytes(), previous)

    def test_failed_atomic_write_preserves_reports_and_pending_commands(self):
        previous = self.path.read_bytes()
        operations = [lambda: self.service.register({"id": "bedroom", "name": "Changed"}),
                      lambda: self.service.report({"id": "bedroom", "firmware": "new"}),
                      lambda: self.service.command("bedroom", "sync")]
        for operation in operations:
            with patch("webclock.services.storage.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    operation()
            self.assertEqual(self.path.read_bytes(), previous)
        command = self.service.command("bedroom", "sync")
        previous = self.path.read_bytes()
        with patch("webclock.services.storage.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.service.report({"id": "bedroom", "acknowledged_commands": [command["id"]]})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(DeviceService(self.path).list()[0]["commands"], [command])
        self.assertEqual(list(self.path.parent.glob(".settings-*")), [])


if __name__ == "__main__":
    unittest.main()
