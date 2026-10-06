"""Join a server-managed group with its six-character invitation."""
import re

from aiohttp import DummyCookieJar
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import ApiError, WebClockClient, normalize_url
from .const import CONF_CODE, CONF_EMIT, CONF_TOKEN, CONF_URL, DOMAIN


class WebClockConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _client = None

    async def async_step_user(self, user_input=None):
        return await self._join_form("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._join_form("reauth_confirm", user_input)

    async def _join_form(self, step, user_input):
        errors = {}
        entry = self._get_reauth_entry() if step == "reauth_confirm" else None
        if user_input:
            try:
                url = normalize_url(entry.data[CONF_URL] if entry else user_input[CONF_URL])
                code = user_input[CONF_CODE].strip().upper()
                if not re.fullmatch(r"[A-Z0-9]{6}", code):
                    raise ValueError("invalid_code")
                if self._client is None or self._client.url != url:
                    session = async_create_clientsession(self.hass, cookie_jar=DummyCookieJar())
                    self._client = WebClockClient(session, url)
                identity = await self._client.join(code)
            except ValueError as error:
                errors["base"] = "invalid_code" if str(error) == "invalid_code" else "invalid_url"
            except ApiError as error:
                errors["base"] = error.code if error.code in {
                    "invalid_invitation", "rate_limited", "https_required", "join_attempt_conflict"
                } else "cannot_connect"
            else:
                data = {CONF_URL: url, CONF_TOKEN: self._client.token, "device_id": identity["device_id"]}
                unique_id = url + "|" + identity["device_id"]
                if entry:
                    return self.async_update_reload_and_abort(entry, data=data, unique_id=unique_id)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="WebClock", data=data)
        fields = {}
        if not entry:
            fields[vol.Required(CONF_URL)] = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
        fields[vol.Required(CONF_CODE)] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
        schema = self.add_suggested_values_to_schema(vol.Schema(fields), user_input or {})
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WebClockOptionsFlow()


class WebClockOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Optional(CONF_EMIT, default=self.config_entry.options.get(CONF_EMIT, False)): bool,
        }))
