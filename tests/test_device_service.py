"""Central device management: python3 -m unittest discover -s tests -p test_device_service.py."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webclock.services.device_service import CAPABILITY_FIELDS, DeviceService, REPORT_FIELDS
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
                         {"id", "name", "reported_name", "admin_name", "device_type", "capabilities",
                          "capabilities_reported_at", "registered_at", "last_seen", "online", "commands",
                          "sync_status"})
        self.assertIsNone(response["device"]["admin_name"])
        self.assertIsNone(response["device"]["device_type"])
        self.assertIsNone(response["device"]["capabilities"])
        self.assertIsNone(response["device"]["capabilities_reported_at"])
        self.assertEqual(response["device"]["sync_status"], {"state": "idle"})
        renamed = self.service.register({"id": "bedroom", "name": " New name "})
        self.assertEqual(renamed["name"], "New name")
        self.assertEqual(renamed["reported_name"], "New name")
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

    def test_administrator_name_survives_registration_reports_and_restart(self):
        renamed = self.service.rename("bedroom", {"name": " Hall clock "})
        self.assertEqual(renamed["name"], "Hall clock")
        self.assertEqual(renamed["admin_name"], "Hall clock")
        self.assertEqual(renamed["reported_name"], "Bedroom")
        registered = self.service.register({"id": "bedroom", "name": "Self-reported"})
        self.assertEqual(registered["name"], "Hall clock")
        self.assertEqual(registered["reported_name"], "Self-reported")
        reported = self.service.report({"id": "bedroom", "firmware": "1.0"})["device"]
        self.assertEqual(reported["name"], "Hall clock")
        self.assertEqual(DeviceService(self.path).list()[0], reported)

    def test_legacy_name_only_record_is_read_and_upgraded_without_losing_the_reported_name(self):
        legacy = {"bedroom": {"id": "bedroom", "name": "Legacy name",
                              "registered_at": "2026-10-03T00:00:00+00:00", "commands": []}}
        save_json(self.path, legacy)
        before = self.path.read_bytes()
        listed = DeviceService(self.path).list()[0]
        self.assertEqual(listed["name"], "Legacy name")
        self.assertEqual(listed["reported_name"], "Legacy name")
        self.assertIsNone(listed["admin_name"])
        self.assertIsNone(listed["capabilities"])
        self.assertEqual(self.path.read_bytes(), before)
        renamed = DeviceService(self.path).rename("bedroom", {"name": "Managed name"})
        self.assertEqual(renamed["name"], "Managed name")
        self.assertEqual(renamed["reported_name"], "Legacy name")
        reregistered = DeviceService(self.path).register({"id": "bedroom", "name": "New report"})
        self.assertEqual(reregistered["name"], "Managed name")
        self.assertEqual(reregistered["reported_name"], "New report")

    def test_optional_type_and_capabilities_are_partial_observations(self):
        registered = self.service.register({
            "id": "bedroom", "name": "Bedroom", "device_type": " esp32-s3 ",
            "capabilities": {"display": True, "audio": False}})
        self.assertEqual(registered["device_type"], "esp32-s3")
        self.assertEqual(registered["capabilities"], {"display": True, "audio": False})
        first_reported_at = registered["capabilities_reported_at"]
        unchanged = self.service.report({"id": "bedroom"})["device"]
        self.assertEqual(unchanged["capabilities_reported_at"], first_reported_at)
        updated = self.service.report({
            "id": "bedroom", "device_type": "browser",
            "capabilities": {"calendar": True, "background": False}})["device"]
        self.assertEqual(updated["device_type"], "browser")
        self.assertEqual(updated["capabilities"], {"calendar": True, "background": False})
        self.assertTrue(updated["capabilities_reported_at"])
        self.assertEqual(DeviceService(self.path).list()[0], updated)

    def test_new_device_fields_reject_empty_long_unknown_and_invalid_values(self):
        previous = self.path.read_bytes()
        invalid = [
            lambda: self.service.rename("bedroom", {"name": ""}),
            lambda: self.service.rename("bedroom", {"name": "x" * 101}),
            lambda: self.service.rename("bedroom", {"name": "Name", "extra": True}),
            lambda: self.service.register({"id": "bedroom", "name": "Name", "device_type": ""}),
            lambda: self.service.register({"id": "bedroom", "name": "Name", "device_type": "x" * 51}),
            lambda: self.service.register({"id": "bedroom", "name": "Name", "capabilities": {}}),
            lambda: self.service.report({"id": "bedroom", "capabilities": {"unknown": True}}),
            lambda: self.service.report({"id": "bedroom", "capabilities": {"audio": 1}}),
        ]
        self.assertEqual(CAPABILITY_FIELDS,
                         {"display", "audio", "notifications", "background", "calendar"})
        for operation in invalid:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation()
            self.assertEqual(self.path.read_bytes(), previous)

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

    def test_sync_confirmation_timeout_late_ack_and_restart_persistence(self):
        requested = "2026-10-05T00:00:00+00:00"
        with patch("webclock.services.device_service._now", return_value=requested):
            command = self.service.command("bedroom", "sync")
            self.assertEqual(command["created_at"], requested)
            pending = self.service.list()[0]["sync_status"]
        self.assertEqual(pending["state"], "pending")
        self.assertEqual(pending["command_id"], command["id"])
        self.assertEqual(pending["timeout_at"], "2026-10-05T00:05:00+00:00")
        with patch("webclock.services.device_service._now", return_value="2026-10-05T00:06:00+00:00"):
            self.assertEqual(self.service.command("bedroom", "sync"), command)
            timed_out = DeviceService(self.path).list()[0]
        self.assertEqual(timed_out["sync_status"]["state"], "timed_out")
        self.assertEqual(timed_out["commands"], [command], "Timeout must not delete the pending command")
        with patch("webclock.services.device_service._now", return_value="2026-10-05T00:07:00+00:00"):
            confirmed = self.service.report({
                "id": "bedroom", "acknowledged_commands": [command["id"]]})["device"]
        self.assertEqual(confirmed["commands"], [])
        self.assertEqual(confirmed["sync_status"], {
            "state": "confirmed", "command_id": command["id"], "requested_at": requested,
            "acknowledged_at": "2026-10-05T00:07:00+00:00"})
        self.assertEqual(DeviceService(self.path).list()[0]["sync_status"], confirmed["sync_status"])
        duplicate = self.service.report({
            "id": "bedroom", "acknowledged_commands": [command["id"], "unknown"]})["device"]
        self.assertEqual(duplicate["sync_status"], confirmed["sync_status"],
                         "Duplicate or unknown ACKs must not invent a newer confirmation")

    def test_other_device_and_unknown_ack_never_confirm_a_pending_command(self):
        self.service.register({"id": "office", "name": "Office"})
        command = self.service.command("bedroom", "sync")
        office = self.service.report({
            "id": "office", "acknowledged_commands": [command["id"], "unknown"]})["device"]
        self.assertEqual(office["sync_status"], {"state": "idle"})
        bedroom = self.service.report({
            "id": "bedroom", "acknowledged_commands": ["unknown"]})["device"]
        self.assertEqual(bedroom["sync_status"]["state"], "pending")
        self.assertEqual(bedroom["commands"], [command])

    def test_previous_ack_cannot_confirm_next_sync_and_failed_ack_can_be_retried(self):
        first = self.service.command("bedroom", "sync")
        confirmed = self.service.report({
            "id": "bedroom", "acknowledged_commands": [first["id"]]})["device"]
        previous_ack = load_json(self.path, {})["bedroom"]["last_sync_ack"]
        second = self.service.command("bedroom", "sync")
        self.assertNotEqual(second["id"], first["id"])

        repeated = DeviceService(self.path).report({
            "id": "bedroom", "acknowledged_commands": [first["id"]]})["device"]
        self.assertEqual(repeated["commands"], [second])
        self.assertEqual(repeated["sync_status"]["command_id"], second["id"])
        self.assertEqual(repeated["sync_status"]["state"], "pending")
        self.assertEqual(load_json(self.path, {})["bedroom"]["last_sync_ack"], previous_ack)

        before = self.path.read_bytes()
        with patch("webclock.services.storage.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.service.report({
                    "id": "bedroom", "acknowledged_commands": [second["id"]]})
        self.assertEqual(self.path.read_bytes(), before)
        restarted = DeviceService(self.path)
        self.assertEqual(restarted.list()[0]["commands"], [second])
        retried = restarted.report({
            "id": "bedroom", "acknowledged_commands": [second["id"]]})["device"]
        self.assertEqual(retried["commands"], [])
        self.assertEqual(retried["sync_status"]["state"], "confirmed")
        self.assertEqual(retried["sync_status"]["command_id"], second["id"])
        self.assertNotEqual(retried["sync_status"], confirmed["sync_status"])
        self.assertEqual(DeviceService(self.path).report({
            "id": "bedroom", "acknowledged_commands": [first["id"]]})["device"]["sync_status"],
            retried["sync_status"])

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
        operations = [lambda: self.service.rename("bedroom", {"name": "Managed"}),
                      lambda: self.service.register({"id": "bedroom", "name": "Changed"}),
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
