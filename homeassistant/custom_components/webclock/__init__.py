"""WebClock managed display integration."""
from pathlib import Path

from aiohttp import DummyCookieJar
import voluptuous as vol

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ApiError, WebClockClient
from .const import CONF_TOKEN, CONF_URL, DOMAIN, VERSION
from .coordinator import WebClockCoordinator


async def async_setup(hass, config):
    await hass.http.async_register_static_paths([
        StaticPathConfig("/webclock/webclock-cards.js", str(Path(__file__).parent / "www/webclock-cards.js"), False)
    ])
    frontend.add_extra_js_url(hass, "/webclock/webclock-cards.js?v=" + VERSION)
    websocket_api.async_register_command(hass, websocket_time)
    return True


@websocket_api.websocket_command({vol.Required("type"): "webclock/time", vol.Required("entry_id"): str})
@callback
def websocket_time(hass, connection, msg):
    """Return only the calibrated public clock, never private group data."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    coordinator = getattr(entry, "runtime_data", None) if entry and entry.domain == DOMAIN else None
    if coordinator is None or coordinator.server_now() is None or coordinator._closed:
        connection.send_error(msg["id"], "not_ready", "Clock not calibrated")
        return
    connection.send_result(msg["id"], {"server_timestamp": coordinator.server_now()})


async def async_setup_entry(hass, entry):
    session = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
    client = WebClockClient(session, entry.data[CONF_URL], entry.data[CONF_TOKEN])
    coordinator = WebClockCoordinator(hass, entry, client)
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.close)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])


async def async_remove_entry(hass, entry):
    session = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
    client = WebClockClient(session, entry.data[CONF_URL], entry.data[CONF_TOKEN])
    try:
        await client.request("token/leave", {})
    except ApiError:
        # Server can be offline; the administrator can remove its record later.
        pass
