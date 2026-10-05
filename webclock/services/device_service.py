"""Persist device reports and commands until the device acknowledges them."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from uuid import uuid4

from .storage import load_json, save_json, storage_lock

REPORT_FIELDS = {"firmware", "config_revision", "schedule_revision", "holiday_revision"}
CAPABILITY_FIELDS = {"display", "audio", "notifications", "background", "calendar"}
SYNC_ACK_TIMEOUT_SECONDS = 300


def _text(value, field, maximum=128):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string (max {maximum})")
    return value.strip()


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("id must contain 1-64 letters, numbers, underscores or hyphens")
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


def _capabilities(value):
    if not isinstance(value, dict) or not value or set(value) - CAPABILITY_FIELDS:
        raise ValueError("capabilities must be a non-empty object with known fields")
    if any(type(supported) is not bool for supported in value.values()):
        raise ValueError("capability values must be booleans")
    return deepcopy(value)


def _sync_status(device):
    pending = [command for command in device.get("commands", []) if command.get("action") == "sync"]
    if pending:
        command = pending[0]
        requested_at = command.get("created_at")
        try:
            timeout = datetime.fromisoformat(requested_at) + timedelta(seconds=SYNC_ACK_TIMEOUT_SECONDS)
            timed_out = datetime.fromisoformat(_now()) >= timeout
            timeout_at = timeout.isoformat()
        except (TypeError, ValueError):
            timed_out, timeout_at = False, None
        return {"state": "timed_out" if timed_out else "pending",
                "command_id": command.get("id"), "requested_at": requested_at,
                "timeout_at": timeout_at}
    acknowledged = device.get("last_sync_ack")
    if isinstance(acknowledged, dict):
        return {"state": "confirmed",
                "command_id": acknowledged.get("command_id"),
                "requested_at": acknowledged.get("requested_at"),
                "acknowledged_at": acknowledged.get("acknowledged_at")}
    return {"state": "idle"}


class DeviceService:
    def __init__(self, state_path):
        self.path = state_path

    def _load(self):
        devices = load_json(self.path, {})
        if not isinstance(devices, dict):
            raise ValueError("Invalid stored device data")
        return devices

    @staticmethod
    def _public(device):
        fields = {"id", "registered_at", "last_seen"} | REPORT_FIELDS
        result = {key: deepcopy(value) for key, value in device.items() if key in fields}
        reported_name = device.get("reported_name", device.get("name"))
        admin_name = device.get("admin_name")
        result.update(name=admin_name or reported_name,
                      reported_name=reported_name,
                      admin_name=admin_name,
                      device_type=deepcopy(device.get("device_type")),
                      capabilities=deepcopy(device.get("capabilities")),
                      capabilities_reported_at=device.get("capabilities_reported_at"))
        result["commands"] = [
            {key: deepcopy(command[key]) for key in ("id", "action", "created_at") if key in command}
            for command in device.get("commands", []) if command.get("action") == "sync"
        ]
        result["sync_status"] = _sync_status(device)
        last_seen = result.get("last_seen")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen)).total_seconds() if last_seen else None
        result["online"] = age is not None and 0 <= age < 120
        return result

    def register(self, data, authorized_ids=None):
        fields = {"id", "name", "device_type", "capabilities"}
        if not isinstance(data, dict) or set(data) - fields:
            raise ValueError("Invalid registration fields")
        device_id = _identifier(data.get("id"))
        name = _text(data.get("name"), "name", 100)
        device_type = _text(data["device_type"], "device_type", 50) if "device_type" in data else None
        capabilities = _capabilities(data["capabilities"]) if "capabilities" in data else None
        with storage_lock:
            devices = self._load()
            if device_id not in devices and len(devices) >= 100 and authorized_ids is not None:
                # Managed mode cannot use legacy observations as authority.
                # Prune only at capacity, in the same write as the new report.
                devices = {key: row for key, row in devices.items() if key in authorized_ids}
            if device_id not in devices and len(devices) >= 100:
                raise ValueError("Device limit reached (100)")
            device = devices.get(device_id, {"id": device_id, "registered_at": _now(), "commands": []})
            device.setdefault("reported_name", device.get("name", name))
            device["reported_name"] = name
            device["name"] = device.get("admin_name") or name
            if device_type is not None:
                device["device_type"] = device_type
            if capabilities is not None:
                device["capabilities"] = capabilities
                device["capabilities_reported_at"] = _now()
            devices[device_id] = device
            save_json(self.path, devices)
            return self._public(device)

    def report(self, data):
        fields = {"id", "acknowledged_commands", "device_type", "capabilities"} | REPORT_FIELDS
        if not isinstance(data, dict) or set(data) - fields:
            raise ValueError("Invalid device status fields")
        device_id = _identifier(data.get("id"))
        report = {key: _text(data[key], key) for key in REPORT_FIELDS if key in data}
        if "device_type" in data:
            report["device_type"] = _text(data["device_type"], "device_type", 50)
        if "capabilities" in data:
            report["capabilities"] = _capabilities(data["capabilities"])
            report["capabilities_reported_at"] = _now()
        acknowledgements = data.get("acknowledged_commands", [])
        if not isinstance(acknowledgements, list) or len(acknowledgements) > 100:
            raise ValueError("acknowledged_commands must be a list (max 100)")
        for command_id in acknowledgements:
            _identifier(command_id)
        report["last_seen"] = _now()
        with storage_lock:
            devices = self._load()
            if device_id not in devices:
                raise KeyError(device_id)
            device = devices[device_id]
            device.update(report)
            acknowledged = [command for command in device["commands"]
                            if command.get("action") == "sync" and command.get("id") in acknowledgements]
            if acknowledged:
                command = acknowledged[-1]
                device["last_sync_ack"] = {"command_id": command.get("id"),
                                           "requested_at": command.get("created_at"),
                                           "acknowledged_at": report["last_seen"]}
            device["commands"] = [command for command in device["commands"]
                                  if command.get("action") != "sync" or command["id"] not in acknowledgements]
            save_json(self.path, devices)
            public = self._public(device)
            return {"device": public, "commands": deepcopy(public["commands"])}

    def rename(self, device_id, data):
        device_id = _identifier(device_id)
        if not isinstance(data, dict) or set(data) != {"name"}:
            raise ValueError("Expected one administrator name")
        name = _text(data["name"], "name", 100)
        with storage_lock:
            devices = self._load()
            if device_id not in devices:
                raise KeyError(device_id)
            device = devices[device_id]
            device.setdefault("reported_name", device.get("name"))
            device["admin_name"] = name
            device["name"] = name
            save_json(self.path, devices)
            return self._public(device)

    def list(self):
        with storage_lock:
            return [self._public(device) for device in self._load().values()]

    def remove(self, device_id):
        device_id = _identifier(device_id)
        with storage_lock:
            devices = self._load()
            if device_id in devices:
                del devices[device_id]
                save_json(self.path, devices)

    def command(self, device_id, action):
        device_id = _identifier(device_id)
        if action != "sync":
            raise ValueError("Unknown device command")
        with storage_lock:
            devices = self._load()
            if device_id not in devices:
                raise KeyError(device_id)
            commands = devices[device_id]["commands"]
            # Repeated sync requests share one command until acknowledged.
            existing = next(iter(self._public(devices[device_id])["commands"]), None)
            if existing:
                return deepcopy(existing)
            command = {"id": uuid4().hex, "action": action, "created_at": _now()}
            commands.append(command)
            save_json(self.path, devices)
            return deepcopy(command)
