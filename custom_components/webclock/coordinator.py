"""One poller and one alarm executor per enrolled HA instance."""
from __future__ import annotations

from datetime import timedelta
import logging
from time import monotonic, time

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError
from .const import CONF_EMIT, DOMAIN

_LOGGER = logging.getLogger(__name__)


class WebClockCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(seconds=15))
        self.client = client
        self.entry = entry
        self.clock_anchor = None
        self.sampled_at = None
        self.private_valid = False
        self.deadline = 0
        self.wall_deadline = 0
        self._lease_timer = None
        self._alarm_timers = []
        self._acknowledgements = []
        self._closed = False
        self._fired = {}
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.fired")

    async def _async_setup(self):
        saved = await self._store.async_load()
        if saved is not None and (not isinstance(saved, dict) or not all(
                isinstance(key, str) and type(value) in (int, float) for key, value in saved.items())):
            raise UpdateFailed("Invalid alarm delivery history")
        self._fired = saved or {}

    def server_now(self):
        if self.clock_anchor is None:
            return None
        return self.clock_anchor + (monotonic() - self.sampled_at) * 1000

    def lease_valid(self):
        return self.private_valid and monotonic() < self.deadline and time() < self.wall_deadline

    async def _async_update_data(self):
        try:
            result = await self.client.snapshot(self._acknowledgements)
        except ApiError as error:
            if error.status in (401, 403, 409) or error.code == "invalid_response":
                self._clear_private()
            if error.status == 401:
                raise ConfigEntryAuthFailed("Rejoin with a new WebClock invitation") from None
            raise UpdateFailed(error.code) from None
        if self._closed:
            raise UpdateFailed("Integration unloaded")
        self.clock_anchor = result["alarms"]["server_timestamp"]
        self.sampled_at = result["sampled_at"]
        expiry = min(result[key]["lease"]["expires_at"] for key in ("display", "alarms"))
        remaining = (expiry - self.server_now()) / 1000
        if remaining <= 0:
            self._clear_private()
            raise UpdateFailed("Authorization lease expired")
        self.private_valid = True
        self.deadline = monotonic() + remaining
        self.wall_deadline = time() + remaining
        if self._lease_timer:
            self._lease_timer.cancel()
        self._lease_timer = self.hass.loop.call_later(remaining, self._clear_private)
        # Acknowledge only sync requests received BEFORE this successful full fetch.
        self._acknowledgements = [row["id"] for row in result["status"].get("commands", [])
                                  if row.get("action") == "sync" and isinstance(row.get("id"), str)]
        self._schedule_alarms(result)
        return result

    def _cancel_alarms(self):
        for timer in self._alarm_timers:
            timer.cancel()
        self._alarm_timers.clear()

    def _clear_private(self):
        self.private_valid = False
        self._cancel_alarms()
        self._acknowledgements = []
        if self._lease_timer:
            self._lease_timer.cancel()
            self._lease_timer = None
        if self.data:
            self.data = {**self.data,
                         "display": {**self.data["display"], "events": [], "next_event": None},
                         "alarms": {**self.data["alarms"], "alarms": [], "enabled_count": 0}}
            self.async_update_listeners()

    def _schedule_alarms(self, result):
        self._cancel_alarms()
        if not self.entry.options.get(CONF_EMIT, False):
            return
        now = self.server_now()
        identity = result["display"]["identity"]["identity_revision"]
        for alarm in result["alarms"]["alarms"]:
            # No replay after restart, resume or an offline gap.
            delay = (alarm["starts_at"] - now) / 1000
            if delay <= 0 or delay >= self.deadline - monotonic():
                continue
            key = result["display"]["identity"]["device_id"] + ":" + alarm["occurrence_id"]
            if key in self._fired:
                continue
            self._alarm_timers.append(self.hass.loop.call_later(
                delay, self._start_alarm, alarm, key, identity))

    def _start_alarm(self, alarm, key, identity):
        if not self._closed:
            self.hass.async_create_task(self._fire_alarm(alarm, key, identity))

    async def _fire_alarm(self, alarm, key, identity):
        if (self._closed or not self.lease_valid() or key in self._fired
                or not self.entry.options.get(CONF_EMIT, False)
                or self.data["display"]["identity"]["identity_revision"] != identity):
            return
        # Persist before publishing: a crash can lose an event, but never replay it.
        # ponytail: at-most-once local delivery; distributed speaker coordination belongs to HA automations.
        now = self.server_now()
        if not 0 <= now - alarm["starts_at"] < 2000:
            return
        self._fired = {key: value for key, value in self._fired.items() if value > now - 86_400_000}
        self._fired[key] = alarm["starts_at"]
        try:
            await self._store.async_save(self._fired)
        except (OSError, ValueError):
            _LOGGER.error("Unable to persist WebClock alarm delivery; event suppressed")
            return
        if (self._closed or not self.lease_valid()
                or not 0 <= self.server_now() - alarm["starts_at"] < 2000
                or self.data["display"]["identity"]["identity_revision"] != identity
                or alarm not in self.data["alarms"]["alarms"]):
            return
        self.hass.bus.async_fire("webclock_alarm", {
            "entry_id": self.entry.entry_id, "device_id": self.data["display"]["identity"]["device_id"],
            "occurrence_id": alarm["occurrence_id"], "alarm_id": alarm["id"],
            "name": alarm["name"], "starts_at": alarm["starts_at"],
        })

    def close(self):
        self._closed = True
        self._clear_private()
