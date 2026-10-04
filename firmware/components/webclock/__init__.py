"""WebClock schema-2 client for the ESP32-S3 prototype."""
from urllib.parse import urlsplit

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import output, time
from esphome.components.esp32 import include_builtin_idf_component
from esphome.const import CONF_ID

DEPENDENCIES = ["esp32", "wifi", "psram", "time", "output", "display"]
AUTO_LOAD = ["json"]
namespace = cg.esphome_ns.namespace("webclock")
WebClock = namespace.class_("WebClock", cg.Component)


def server_url(value):
    value = cv.string_strict(value).rstrip("/")
    url = urlsplit(value)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username
            or url.password or url.query or url.fragment or any(ord(c) < 32 for c in value)):
        raise cv.Invalid("Use an HTTP(S) server base URL without credentials, query or fragment")
    return value


def token(value):
    value = cv.string_strict(value)
    if len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise cv.Invalid("API token must be at most 512 characters without control characters")
    return value


def device_name(value):
    value = cv.string_strict(value).strip()
    if not value or len(value) > 100:
        raise cv.Invalid("Device name must contain 1-100 characters")
    return value


CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(): cv.declare_id(WebClock),
    cv.Required("time_id"): cv.use_id(time.RealTimeClock),
    cv.Required("buzzer_id"): cv.use_id(output.FloatOutput),
    cv.Required("server_url"): server_url,
    cv.Optional("api_token", default=""): token,
    cv.Optional("device_name", default="WebClock ESP32-S3"): device_name,
    cv.Optional("volume_limit", default=0.25): cv.float_range(min=0, max=0.5),
}).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    include_builtin_idf_component("esp_http_client")
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_clock(await cg.get_variable(config["time_id"])))
    cg.add(var.set_buzzer(await cg.get_variable(config["buzzer_id"])))
    for key in ("server_url", "api_token", "device_name", "volume_limit"):
        cg.add(getattr(var, "set_" + key)(config[key]))
