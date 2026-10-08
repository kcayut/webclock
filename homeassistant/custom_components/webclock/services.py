"""Explicit, revision-checked writes through a separate program credential."""
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import ApiError
from .const import CONF_WRITE_TOKEN, DOMAIN

IDENTIFIER = vol.All(str, vol.Match(r"^[A-Za-z0-9_-]{1,128}$"))
REVISION = vol.All(str, vol.Match(r"^[a-f0-9]{64}$"))
TARGET_FIELDS = {vol.Required("resource"): vol.In(("schedules", "events")),
                 vol.Required("id"): IDENTIFIER,
                 vol.Required("target_kind"): vol.In(("group", "device")),
                 vol.Required("target_id"): IDENTIFIER}


@callback
def register_services(hass):
    async def handle(call):
        entries = hass.config_entries.async_entries(DOMAIN)
        entry = entries[0] if len(entries) == 1 else None
        coordinator = getattr(entry, "runtime_data", None)
        if entry is None or entry.state is not ConfigEntryState.LOADED or coordinator is None or coordinator._closed:
            raise ServiceValidationError("WebClock integration is not loaded")
        token = entry.options.get(CONF_WRITE_TOKEN)
        if not token:
            raise ServiceValidationError("Configure a WebClock write token in integration options")
        data = call.data
        if call.service == "list_calendar_events":
            try:
                return await coordinator.client.calendar_catalog(data["source_ids"], token=token)
            except ApiError as error:
                error_type = ServiceValidationError if 400 <= error.status < 500 else HomeAssistantError
                raise error_type("WebClock: " + error.code) from None
        target = call.service in ("get_target", "assign_content")
        if target:
            resource = data["resource"]
            method = "GET" if call.service == "get_target" else "PUT"
            body = None if method == "GET" else {"assigned": data["assigned"], "revision": data["revision"]}
        else:
            operation, kind = call.service.split("_", 1)
            resource = "schedules" if kind in ("alarm", "alarms") else "events"
            field = "schedule" if resource == "schedules" else "event"
            method = {"list": "GET", "create": "POST", "update": "PATCH", "delete": "DELETE"}[operation]
            body = None if method == "GET" else {
                key: data[key] for key in ("request_id", "revision", field) if key in data
            }
        try:
            return await coordinator.client.control(method, resource, body, data.get("id"),
                data.get("target_kind"), data.get("target_id"), token=token)
        except ApiError as error:
            error_type = ServiceValidationError if 400 <= error.status < 500 else HomeAssistantError
            raise error_type("WebClock: " + error.code) from None

    for kind, field in (("alarm", "schedule"), ("event", "event")):
        for operation in ("list", "create", "update", "delete"):
            fields = {}
            if operation in ("update", "delete"):
                fields.update({vol.Required("id"): IDENTIFIER, vol.Required("revision"): REVISION})
            if operation == "create":
                fields[vol.Required("request_id")] = vol.All(str, vol.Match(r"^[A-Za-z0-9_-]{8,128}$"))
            if operation in ("create", "update"):
                fields[vol.Required(field)] = dict
            name = operation + "_" + kind + ("s" if operation == "list" else "")
            hass.services.async_register(DOMAIN, name, handle, schema=vol.Schema(fields),
                                         supports_response=SupportsResponse.OPTIONAL)
    for name in ("get_target", "assign_content"):
        fields = dict(TARGET_FIELDS)
        if name == "assign_content":
            fields.update({vol.Required("assigned"): bool, vol.Required("revision"): REVISION})
        hass.services.async_register(DOMAIN, name, handle, schema=vol.Schema(fields),
                                     supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "list_calendar_events", handle,
        schema=vol.Schema({vol.Required("source_ids"): vol.All([IDENTIFIER], vol.Length(min=1, max=50))}),
        supports_response=SupportsResponse.OPTIONAL)
