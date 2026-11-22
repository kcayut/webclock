#pragma once

#include <ArduinoJson.h>
#include <driver/usb_serial_jtag.h>
#include <nvs.h>
#include <lwip/inet.h>
#include "esphome/core/helpers.h"

namespace deskusb {
constexpr size_t max_frame = 1800;
inline std::string frame;
inline bool discard = false;
inline uint32_t deadline = 0;
inline bool active() { return deadline != 0; }
inline void clear() { frame.clear(); discard = false; deadline = 0; }

inline bool text_field(JsonVariantConst field, size_t limit) {
  if (!field.is<const char *>()) return false;
  auto raw = field.as<JsonString>();
  if (raw.size() > limit) return false;
  for (size_t i = 0; i < raw.size(); ++i)
    if ((unsigned char) raw.c_str()[i] < 32 || raw.c_str()[i] == 127) return false;
  return true;
}
inline bool valid(JsonDocument &doc) {
  if (!text_field(doc["url"], 320) || !text_field(doc["control"], 512) ||
      !text_field(doc["display"], 512) || doc["control"].as<JsonString>().size() == 0) return false;
  std::string url = doc["url"].as<std::string>();
  const auto start = url.find("://");
  if (start == std::string::npos || url.size() <= start+3 || url[start+3] == '/' ||
      url.find_first_of("@?# \\") != std::string::npos) return false;
  if (url.starts_with("https://")) return true;
  if (!url.starts_with("http://") || !doc["local_http"].is<bool>() || !doc["local_http"].as<bool>() ||
      doc["display"].as<JsonString>().size() != 0) return false;
  const auto host = url.substr(7, url.find_first_of(":/",7)-7);
  in_addr ip{};
  if (inet_pton(AF_INET, host.c_str(), &ip) != 1) return false;
  const uint32_t n = ntohl(ip.s_addr);
  return (n >> 24) == 10 || (n >> 20) == 0xac1 || (n >> 16) == 0xc0a8;
}
template<class Service> void restore(Service *service) {
  nvs_handle_t h;
  if (nvs_open("desk_usb", NVS_READONLY, &h) != ESP_OK) return;
  size_t size = 0;
  std::string saved;
  if (nvs_get_str(h, "profile", nullptr, &size) == ESP_OK && size && size <= max_frame+1) {
    saved.resize(size);
    if (nvs_get_str(h, "profile", saved.data(), &size) != ESP_OK) saved.clear();
  }
  nvs_close(h);
  JsonDocument doc;
  if (!saved.empty() && !deserializeJson(doc,saved.c_str()) && valid(doc)) {
    service->set_usb_desk_profile(doc["url"].as<std::string>(), doc["control"].as<std::string>(),
                                  doc["display"].as<std::string>());
  }
}
inline void reply(const std::string &message) {
  const std::string line = "\nWCD1 " + message + "\n";
  usb_serial_jtag_write_bytes(line.data(), line.size(), pdMS_TO_TICKS(75));
}
inline bool poll() {
  uint8_t bytes[192];
  int n = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), 0);
  for (int i=0; i<n; ++i) {
    const char ch = bytes[i];
    if (ch != '\n') {
      if (frame.size() >= max_frame) discard = true;
      if (!discard) frame += ch;
      continue;
    }
    std::string message;
    message.swap(frame);
    if (discard) { discard=false; reply("INVALID"); continue; }
    if (message == "WCD1 HELLO") { reply("READY " + esphome::get_mac_address()); continue; }
    if (!message.starts_with("WCD1 SET ")) continue;
    JsonDocument doc;
    if (deserializeJson(doc,message.c_str()+9) || !valid(doc)) { reply("INVALID"); continue; }
    nvs_handle_t h;
    bool ok = false;
    if (nvs_open("desk_usb",NVS_READWRITE,&h) == ESP_OK) {
      ok = nvs_set_str(h,"profile",message.c_str()+9) == ESP_OK && nvs_commit(h) == ESP_OK;
      nvs_close(h);
    }
    reply(ok ? "SAVED" : "STORAGE_ERROR");
    if (ok) return true;
  }
  return false;
}
}  // namespace deskusb
