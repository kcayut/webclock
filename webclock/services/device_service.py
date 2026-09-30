"""Persist device reports and commands until the device acknowledges them."""

from copy import deepcopy
from datetime import datetime, timezone
import re
from uuid import uuid4

from .storage import load_json, save_json, storage_lock

REPORT_FIELDS = {"firmware", "config_revision", "schedule_revision", "holiday_revision"}


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
        fields = {"id", "name", "registered_at", "last_seen"} | REPORT_FIELDS
        result = {key: deepcopy(value) for key, value in device.items() if key in fields}
        result["commands"] = [
            {key: deepcopy(command[key]) for key in ("id", "action", "created_at") if key in command}
            for command in device.get("commands", []) if command.get("action") == "sync"
        ]
        last_seen = result.get("last_seen")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen)).total_seconds() if last_seen else None
        result["online"] = age is not None and 0 <= age < 120
        return result

    def register(self, data):
        if not isinstance(data, dict) or set(data) - {"id", "name"}:
            raise ValueError("Registration accepts id and name only")
        device_id = _identifier(data.get("id"))
        name = _text(data.get("name"), "name", 100)
        with storage_lock:
            devices = self._load()
            if device_id not in devices and len(devices) >= 100:
                raise ValueError("Device limit reached (100)")
            device = devices.get(device_id, {"id": device_id, "registered_at": _now(), "commands": []})
            device["name"] = name
            devices[device_id] = device
            save_json(self.path, devices)
            return self._public(device)

    def report(self, data):
        fields = {"id", "acknowledged_commands"} | REPORT_FIELDS
        if not isinstance(data, dict) or set(data) - fields:
            raise ValueError("Invalid device status fields")
        device_id = _identifier(data.get("id"))
        report = {key: _text(data[key], key) for key in REPORT_FIELDS if key in data}
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
            device["commands"] = [command for command in device["commands"]
                                  if command.get("action") != "sync" or command["id"] not in acknowledgements]
            save_json(self.path, devices)
            public = self._public(device)
            return {"device": public, "commands": deepcopy(public["commands"])}

    def list(self):
        with storage_lock:
            return [self._public(device) for device in self._load().values()]

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
