#pragma once

#include "alarm_core.h"
#include <ArduinoJson.h>
#include <cstring>
#include <set>

namespace esphome::webclock {
inline constexpr size_t MAX_SCHEDULES = 64;

inline bool revision(JsonVariantConst value) {
  if (!value.is<const char *>()) return false;
  const char *text = value.as<const char *>();
  if (strlen(text) != 64) return false;
  return std::all_of(text, text + 64, [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}
inline bool valid_config(JsonObjectConst cfg) {
  return cfg["schema_version"].is<int>() && cfg["schema_version"].as<int>() == 2 &&
         cfg["timezone"].as<std::string>() == "Asia/Taipei" && revision(cfg["config_revision"]) &&
         revision(cfg["schedule_revision"]) && revision(cfg["holiday_revision"]);
}
inline bool same_config(JsonObjectConst a, JsonObjectConst b) {
  return valid_config(a) && valid_config(b) &&
    a["config_revision"].as<std::string>() == b["config_revision"].as<std::string>() &&
    a["schedule_revision"].as<std::string>() == b["schedule_revision"].as<std::string>() &&
    a["holiday_revision"].as<std::string>() == b["holiday_revision"].as<std::string>();
}
inline bool identifier(JsonVariantConst value, size_t max = 80) {
  if (!value.is<const char *>()) return false;
  std::string s = value.as<std::string>();
  return !s.empty() && s.size() <= max && std::all_of(s.begin(), s.end(), [](char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
  });
}
inline bool decode(JsonObjectConst bundle, Snapshot &snapshot) {
  auto config = bundle["config"].as<JsonObjectConst>();
  auto schedules = bundle["schedules"].as<JsonObjectConst>();
  auto holidays = bundle["holidays"].as<JsonObjectConst>();
  if (!valid_config(config) || !schedules["schedules"].is<JsonArrayConst>() ||
      schedules["revision"].as<std::string>() != config["schedule_revision"].as<std::string>() ||
      holidays["revision"].as<std::string>() != config["holiday_revision"].as<std::string>() ||
      !holidays["schema_version"].is<int>() || holidays["schema_version"].as<int>() != 1 ||
      holidays["timezone"].as<std::string>() != "Asia/Taipei" || !holidays["days"].is<JsonObjectConst>()) return false;
  Snapshot result;
  result.config_revision = config["config_revision"].as<std::string>();
  result.schedule_revision = config["schedule_revision"].as<std::string>();
  result.holiday_revision = config["holiday_revision"].as<std::string>();
  int32_t end;
  if (!parse_date(holidays["coverage"]["start"].as<std::string>(), result.holiday_start) ||
      !parse_date(holidays["coverage"]["end"].as<std::string>(), end) || end < result.holiday_start ||
      end - result.holiday_start > 3660) return false;
  result.days.assign(end - result.holiday_start + 1, 0);
  for (JsonPairConst item : holidays["days"].as<JsonObjectConst>()) {
    int32_t day;
    if (!parse_date(item.key().c_str(), day) || day < result.holiday_start || day > end) return false;
    const std::string type = item.value()["type"].as<std::string>();
    if (type != "workday" && type != "holiday") return false;
    result.days[day - result.holiday_start] = type == "workday" ? 1 : 2;
  }
  if (std::find(result.days.begin(), result.days.end(), 0) != result.days.end()) return false;
  auto rows = schedules["schedules"].as<JsonArrayConst>();
  if (rows.size() > MAX_SCHEDULES) return false;  // ponytail: 64 records; raise only after memory/flash validation.
  std::set<std::string> ids;
  for (JsonObjectConst row : rows) {
    if (!identifier(row["id"]) || !ids.insert(row["id"].as<std::string>()).second ||
        !row["enabled"].is<bool>() || !row["skip_holidays"].is<bool>() ||
        !row["rule"].is<JsonObjectConst>() || !row["skipped_occurrences"].is<JsonArrayConst>() ||
        !row["calendar_link"].isNull()) return false;
    const std::string type = row["type"].as<std::string>();
    if (type != "alarm" && type != "reminder" && type != "announcement") return false;
    Schedule schedule;
    schedule.id = row["id"].as<std::string>();
    schedule.enabled = row["enabled"].as<bool>() && type == "alarm";
    schedule.skip_holidays = row["skip_holidays"].as<bool>();
    const std::string when = row["time"].as<std::string>();
    if (when.size() != 5 || when[2] != ':' || when[0] < '0' || when[0] > '2' ||
        when[1] < '0' || when[1] > '9' || when[3] < '0' || when[3] > '5' || when[4] < '0' || when[4] > '9') return false;
    const int hour = (when[0] - '0') * 10 + when[1] - '0';
    if (hour > 23) return false;
    schedule.minute_of_day = hour * 60 + (when[3] - '0') * 10 + when[4] - '0';
    if (!row["browser_volume"].is<int>() || row["browser_volume"].as<int>() < 0 || row["browser_volume"].as<int>() > 100) return false;
    schedule.volume = row["browser_volume"].as<int>();
    const std::string sound = row["browser_sound"].as<std::string>();
    const std::set<std::string> sounds{"bell", "beep", "digital", "chime", "melody", "pulse", "sonar", "silent"};
    if (!sounds.count(sound)) return false;
    schedule.silent = sound == "silent";
    auto rule = row["rule"].as<JsonObjectConst>();
    if (rule.size() > 1) return false;
    schedule.rule = Rule::DAILY;
    if (!rule.isNull() && rule.size()) {
      if (rule["weekdays"].is<JsonArrayConst>()) {
        auto values = rule["weekdays"].as<JsonArrayConst>();
        if (values.size() == 0 || values.size() > 7) return false;
        schedule.rule = Rule::WEEKDAYS;
        for (JsonVariantConst value : values) {
          if (!value.is<int>() || value.as<int>() < 1 || value.as<int>() > 7) return false;
          schedule.weekdays |= 1 << (value.as<int>() - 1);
        }
      } else if (rule["dates"].is<JsonArrayConst>()) {
        auto values = rule["dates"].as<JsonArrayConst>();
        if (values.size() == 0 || values.size() > 366) return false;
        schedule.rule = Rule::DATES;
        for (JsonVariantConst value : values) {
          int32_t day;
          if (!value.is<const char *>() || !parse_date(value.as<std::string>(), day)) return false;
          schedule.dates.push_back(day);
        }
      } else if (rule["workday_only"].is<bool>() && rule["workday_only"].as<bool>()) schedule.rule = Rule::WORKDAY;
      else if (rule["holiday_only"].is<bool>() && rule["holiday_only"].as<bool>()) schedule.rule = Rule::HOLIDAY;
      else return false;
    }
    if (schedule.rule == Rule::HOLIDAY && schedule.skip_holidays) return false;
    auto skipped = row["skipped_occurrences"].as<JsonArrayConst>();
    if (skipped.size() > 3660) return false;
    for (JsonVariantConst value : skipped) {
      int64_t stamp;
      if (!value.is<const char *>() || !parse_skip(value.as<std::string>(), stamp)) return false;
      schedule.skipped.push_back(stamp);
    }
    result.schedules.push_back(std::move(schedule));
  }
  snapshot = std::move(result);
  return true;
}
}  // namespace esphome::webclock
