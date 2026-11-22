#pragma once

#include "sync_codec.h"
#include <cstdio>
#include <ctime>
#include <string>

namespace esphome::webclock {

// USB pairing grants the device its own daily slot. A second, legacy snapshot
// of that slot would still ring after an offline edit or cancellation.
inline bool subscribe_legacy_schedules(bool usb_paired, bool group_display) {
  return !usb_paired && !group_display;
}

// Persist the local value and its last acknowledged ancestor together.
// -1 = new daily slot, -2 = deleted or converted into a server-managed rule.
// The original "daily" preference retains this layout for firmware upgrades.
struct LegacyDeskAlarm {
  int value{-1}, base{-1};
  uint32_t generation{0};
  uint64_t binding{0};
};

struct DeskAlarm : LegacyDeskAlarm {
  int skip{0}, base_skip{0};  // Exact epoch minutes, zero means no skip.
  void save(int next, int next_skip = 0) {
    if (base == -2) { ++generation; base = -1; }
    skip = next_skip;
    value = next;
  }
};

struct DailySetting {
  int value, skip;
  bool operator==(const DailySetting &other) const { return value == other.value && skip == other.skip; }
};
struct DeskAck { DeskAlarm sent; DailySetting remote; int consumed_minute{0}; };

inline void apply_ack(DeskAlarm &state, const DeskAck &ack, int &last_minute) {
  if (state.binding != ack.sent.binding || state.generation != ack.sent.generation ||
      state.base != ack.sent.base || state.base_skip != ack.sent.base_skip) return;
  last_minute = std::max(last_minute, ack.consumed_minute);
  const bool unedited = state.value == ack.sent.value && state.skip == ack.sent.skip;
  if (ack.remote.value == -2 && !unedited) {
    ++state.generation;
    state.base = -1;
    state.base_skip = 0;
    return;
  }
  if (unedited) {
    state.value = ack.remote.value == -2 ? state.value % 1440 : ack.remote.value;
    state.skip = ack.remote.skip;
  }
  state.base = ack.remote.value;
  state.base_skip = ack.remote.skip;
}

inline std::string skip_time(int minute) {
  time_t taipei = int64_t(minute) * 60 + 8 * 3600;
  struct tm civil{};
  char stamp[32];
  if (!gmtime_r(&taipei, &civil) || !strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:00+08:00", &civil))
    return {};
  return stamp;
}

// Returns false on transport/validation/revision failure: keep pending state for retry.
template<class Call>
bool sync_daily(DeskAck &ack, const std::string &device, std::string &item_id, int now_minute, Call call) {
  const auto &state = ack.sent;
  if (state.base == -2 || state.value < 0 || state.value >= 2880) return false;
  auto &result = ack.remote;
  JsonDocument body, doc;
  if (item_id.empty()) {
    // The initial request body must stay identical across edits, restarts and OTA.
    body["request_id"] = device + "-daily-" + std::to_string(state.generation);
    auto row = body["schedule"].to<JsonObject>();
    row["name"] = "桌鐘每日鬧鐘 " + device;
    row["time"] = "07:00";
    row["enabled"] = false;
    int status = call("POST", "/schedules", body, doc);
    if ((status != 200 && status != 201) || !identifier(doc["schedule"]["id"])) return false;
    item_id = doc["schedule"]["id"].as<std::string>();
  }
  const auto path = "/schedules/" + item_id;
  int status = call("GET", path, JsonDocument{}, doc);
  if (status == 404 && doc["code"] == "not_found") { result = {-2, 0}; return true; }
  auto row = doc["schedule"].as<JsonObjectConst>();
  if (status != 200 || !revision(doc["revision"]) || row["id"] != item_id ||
      !row["enabled"].is<bool>() || !row["time"].is<const char *>() ||
      !row["skip_holidays"].is<bool>() || !row["browser_volume"].is<int>() ||
      !row["browser_sound"].is<const char *>() || row["type"] != "alarm" || !row["rule"].is<JsonObjectConst>() ||
      !row["skipped_occurrences"].is<JsonArrayConst>()) return false;
  std::string when = row["time"].as<std::string>();
  int hour, minute;
  if (when.size() != 5 || when[2] != ':' || !alarm_detail::digits(when,0,2,hour) ||
      !alarm_detail::digits(when,3,2,minute) || hour >= 24 || minute >= 60) return false;
  if (row["rule"].size() || !row["calendar_link"].isNull() || row["skip_holidays"] == true ||
      !row["targets"].isNull() ||
      row["browser_sound"] == "silent" || row["browser_volume"] == 0) {
    result = {-2, 0};  // Never turn a restricted or silent web rule into an audible daily alarm.
    return true;
  }
  const auto skips = row["skipped_occurrences"].as<JsonArrayConst>();
  if (now_minute <= 0 && (skips.size() || state.skip || state.base_skip)) return false;
  result = {hour * 60 + minute + (row["enabled"].as<bool>() ? 1440 : 0), 0};
  for (JsonVariantConst entry : skips) {
    int64_t stamp;
    if (!entry.is<const char *>() || !parse_skip(entry.as<std::string>(), stamp)) return false;
    if (stamp < int64_t(now_minute) * 60) continue;
    if (stamp % 60 != 0 || (stamp / 60 + 480) % 1440 != hour * 60 + minute ||
        stamp / 60 > std::numeric_limits<int>::max()) { result = {-2, 0}; return true; }
    // Web can already skip tomorrow during today's skipped minute.
    if (result.skip == now_minute) ack.consumed_minute = now_minute;
    else if (result.skip) { result = {-2, 0}; return true; }
    result.skip = stamp / 60;
  }
  auto active = [now_minute](int skip) { return skip >= now_minute ? skip : 0; };
  const DailySetting ancestor{state.base == -1 ? 420 : state.base, active(state.base_skip)};
  const DailySetting local{state.value, active(state.skip)};
  if (!(result == ancestor) || result == local) return true;
  body.clear();
  body["revision"] = doc["revision"].as<std::string>();
  if (local.skip != result.skip) {
    auto list = body["schedule"]["skipped_occurrences"].to<JsonArray>();
    const auto previous = skip_time(result.skip);
    for (JsonVariantConst entry : skips) {
      // Resume keeps history. A new skip prunes past dates like the web UI.
      if ((!local.skip && entry != previous) ||
          (ack.consumed_minute && entry == skip_time(ack.consumed_minute)))
        list.add(entry);
    }
    if (local.skip) {
      const auto stamp = skip_time(local.skip);
      if (stamp.empty()) return false;
      list.add(stamp);
    }
  }
  char time[6];
  snprintf(time, sizeof(time), "%02u:%02u", unsigned(state.value / 60 % 24), unsigned(state.value % 60));
  body["schedule"]["time"] = time;
  body["schedule"]["enabled"] = state.value >= 1440;
  status = call("PATCH", path, body, doc);
  if (status != 200 || !revision(doc["revision"]) || doc["schedule"]["id"] != item_id ||
      doc["schedule"]["time"] != time || doc["schedule"]["enabled"] != (state.value >= 1440)) return false;
  if (body["schedule"]["skipped_occurrences"].is<JsonArrayConst>() &&
      doc["schedule"]["skipped_occurrences"] != body["schedule"]["skipped_occurrences"]) return false;
  result = local;
  return true;
}

// Milliseconds from the start of the request, including transport and queue latency.
inline uint32_t calendar_line(const JsonDocument &doc, bool scoped, std::string &line) {
  uint32_t duration = 60000;
  line.clear();
  if (doc.overflowed() || !doc["events"].is<JsonArrayConst>()) return 0;
  if (scoped) {
    const auto issued = doc["lease"]["issued_at"], expires = doc["lease"]["expires_at"];
    const int64_t stamp = doc["server_timestamp"] | int64_t{0};
    if (doc["schema_version"] != 3 || stamp <= 0 || !issued.is<int64_t>() ||
        !expires.is<int64_t>() || issued.as<int64_t>() != stamp || expires.as<int64_t>() <= stamp) return 0;
    duration = std::min<int64_t>(duration, expires.as<int64_t>() - stamp);
  }
  for (JsonObjectConst event : doc["events"].as<JsonArrayConst>()) {
    if (!event["text"].is<const char *>()) continue;
    std::string entry = event["text"].as<std::string>();
    if (entry.empty()) continue;
    if (event["time"].is<const char *>() && event["time"] != "")
      entry = event["time"].as<std::string>() + " " + entry;
    if (entry.size() > 2048) {
      size_t end = 2048;
      while ((uint8_t(entry[end]) & 0xc0) == 0x80) --end;
      entry.resize(end);
    }
    if (line.size() + entry.size() + 3 > 8192) break;
    if (!line.empty()) line += " / ";
    line += entry;
  }
  return duration;
}
}  // namespace esphome::webclock
