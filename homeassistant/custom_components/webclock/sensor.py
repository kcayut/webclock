"""Three entities shared by any number of dashboard cards."""
from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(WebClockSensor(entry.runtime_data, key) for key in ("time", "calendar", "alarms"))


class WebClockSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"events", "alarms", "server_timestamp", "lease_expires_at", "next_event"})

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = coordinator.entry.entry_id + "_" + key
        self._attr_translation_key = key
        self._attr_icon = {"time": "mdi:clock-outline", "calendar": "mdi:calendar", "alarms": "mdi:alarm"}[key]
        if key == "time":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)}, name=coordinator.entry.title,
            manufacturer="WebClock", model="Managed Home Assistant display",
        )

    @property
    def available(self):
        if self.key == "time":
            return self.coordinator.clock_anchor is not None
        return self.coordinator.lease_valid()

    @property
    def native_value(self):
        if not self.available:
            return None
        if self.key == "time":
            return datetime.fromtimestamp(self.coordinator.clock_anchor / 1000, timezone.utc)
        data = self.coordinator.data
        return len(data["display"]["events"]) if self.key == "calendar" else data["alarms"]["enabled_count"]

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        attrs = {"webclock_kind": self.key, "entry_id": self.coordinator.entry.entry_id}
        if not data:
            return attrs
        settings = data["display"]["settings"]
        attrs.update({key: settings[key] for key in ("timezone_offset", "time_format", "language")})
        if self.key == "time":
            return attrs
        attrs["lease_expires_at"] = min(data[key]["lease"]["expires_at"] for key in ("display", "alarms"))
        if self.key == "calendar":
            attrs["events"] = data["display"]["events"] if self.available else []
        else:
            attrs["alarms"] = data["alarms"]["alarms"] if self.available else []
            attrs["event_delivery_enabled"] = self.coordinator.entry.options.get("emit_alarm_events", False)
        return attrs
