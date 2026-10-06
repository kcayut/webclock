"""Small cookie-free client for the existing managed-device contract."""
from __future__ import annotations

import asyncio
import json
import math
import re
from time import monotonic
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientError


class ApiError(Exception):
    """A safe error code, never a response body, URL or credential."""

    def __init__(self, code="cannot_connect", status=0):
        super().__init__(code)
        self.code = code
        self.status = status


def normalize_url(value):
    """Require a server origin; credentials, fragments and query strings are not settings."""
    if not isinstance(value, str):
        raise ValueError("invalid_url")
    value = value.strip()
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or any(char.isspace() for char in value)):
        raise ValueError("invalid_url")
    try:
        parsed.port
    except ValueError:
        raise ValueError("invalid_url") from None
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), "", "", ""))


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


class WebClockClient:
    def __init__(self, session, url, token=None):
        self.session = session
        self.url = normalize_url(url)
        self.token = token
        self.attempt_id = None

    async def request(self, path, body=None):
        headers = {"X-WebClock-Client": "native-v1", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            async with asyncio.timeout(15):
                async with self.session.request(
                    "GET" if body is None else "POST", self.url + "/api/v2/device/" + path,
                    json=body, headers=headers, allow_redirects=False,
                ) as response:
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > 2_000_000:
                            raise ApiError("invalid_response", response.status)
                    if response.content_type != "application/json":
                        raise ApiError("invalid_response", response.status)
                    result = json.loads(raw)
                    if not isinstance(result, dict):
                        raise ApiError("invalid_response", response.status)
                    if response.status not in (200, 201):
                        code = result.get("code")
                        allowed = {"invalid_invitation", "rate_limited", "https_required",
                                   "join_attempt_conflict", "device_authentication_required",
                                   "device_authorization_revoked", "display_scope_changed"}
                        raise ApiError(code if code in allowed else "cannot_connect", response.status)
                    return result
        except (ClientError, TimeoutError):
            raise ApiError() from None
        except (UnicodeError, json.JSONDecodeError):
            raise ApiError("invalid_response") from None

    async def join(self, code):
        # Keep the prepared secret across retries, including a lost successful reply.
        if self.attempt_id is None:
            prepared = await self.request("token/prepare", {})
            if (not isinstance(prepared.get("token"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{43}", prepared["token"])
                    or not isinstance(prepared.get("attempt_id"), str)):
                raise ApiError("invalid_response")
            self.token, self.attempt_id = prepared["token"], prepared["attempt_id"]
        try:
            result = await self.request("token/join", {"attempt_id": self.attempt_id, "code": code})
        except ApiError as error:
            if error.code == "join_attempt_conflict":
                self.token = self.attempt_id = None
            raise
        identity = result.get("identity", {})
        if result.get("schema_version") != 3 or not isinstance(identity.get("device_id"), str):
            raise ApiError("invalid_response")
        return identity

    async def snapshot(self, acknowledgements=()):
        display = await self.request("display")
        alarms = await self.request("browser-alarms")
        self.validate_snapshot(display, alarms)
        # Capture the server clock before status I/O, then advance using monotonic time.
        sampled_at = monotonic()
        status = await self.request("status", {
            "name": "Home Assistant", "device_type": "homeassistant", "firmware": "ha-1.0.0",
            "capabilities": {"display": True, "calendar": True, "background": True, "audio": False},
            **{key: display[key] for key in ("config_revision", "schedule_revision", "holiday_revision")},
            "acknowledged_commands": list(acknowledgements),
        })
        if status.get("identity") != display["identity"]:
            raise ApiError("display_scope_changed", 409)
        commands = status.get("commands")
        if (status.get("schema_version") != 3 or not isinstance(commands, list) or len(commands) > 100
                or not all(isinstance(row, dict) and row.get("action") == "sync"
                           and isinstance(row.get("id"), str)
                           and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row["id"]) for row in commands)):
            raise ApiError("invalid_response")
        return {"display": display, "alarms": alarms, "status": status, "sampled_at": sampled_at}

    @staticmethod
    def validate_snapshot(display, alarms):
        for data in (display, alarms):
            identity = data.get("identity")
            lease = data.get("lease")
            if (data.get("schema_version") != 3 or not isinstance(identity, dict)
                    or not all(isinstance(identity.get(key), str) and identity[key]
                               for key in ("device_id", "group_id", "identity_revision"))
                    or not all(isinstance(data.get(key), str) and data[key]
                               for key in ("config_revision", "schedule_revision", "holiday_revision"))
                    or not number(data.get("server_timestamp")) or not isinstance(lease, dict)
                    or not 0 < data["server_timestamp"] < 253_402_300_800_000
                    or not number(lease.get("expires_at")) or not number(lease.get("issued_at"))
                    or not 0 < lease["expires_at"] - data["server_timestamp"] <= 300_000):
                raise ApiError("invalid_response")
        if any(display[key] != alarms[key] for key in
               ("identity", "config_revision", "schedule_revision", "holiday_revision")):
            raise ApiError("display_scope_changed", 409)
        settings = display.get("settings")
        if (not isinstance(settings, dict) or not number(settings.get("timezone_offset"))
                or not -12 <= settings["timezone_offset"] <= 14
                or settings.get("time_format") not in ("12h", "24h")
                or settings.get("language") not in ("zh-TW", "en", "ja")
                or not isinstance(display.get("events"), list)
                or not all(isinstance(row, dict) and isinstance(row.get("text"), str)
                           and isinstance(row.get("time"), str) for row in display["events"])
                or not isinstance(alarms.get("alarms"), list)
                or type(alarms.get("enabled_count")) is not int or alarms["enabled_count"] < 0
                or len(alarms["alarms"]) > 1000):
            raise ApiError("invalid_response")
        for row in alarms["alarms"]:
            if (not isinstance(row, dict) or not number(row.get("starts_at"))
                    or not 0 < row["starts_at"] < 253_402_300_800_000
                    or not all(isinstance(row.get(key), str) and row[key] for key in ("id", "occurrence_id"))
                    or not isinstance(row.get("name"), str)):
                raise ApiError("invalid_response")
