#pragma once

#include <algorithm>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

namespace esphome {
namespace webclock {

enum class Rule { DAILY, WEEKDAYS, DATES, WORKDAY, HOLIDAY };

struct Schedule {
  std::string id;
  uint16_t minute_of_day{0};
  bool enabled{true};
  Rule rule{Rule::DAILY};
  uint8_t weekdays{0};  // Bit 0 is ISO Monday, bit 6 is Sunday.
  bool skip_holidays{false};
  bool silent{false};
  uint8_t volume{100};
  std::vector<int32_t> dates;   // Taipei civil dates as days since 1970-01-01.
  std::vector<int64_t> skipped;  // Exact UTC seconds; see NON_MINUTE_SKIP below.
};

struct Snapshot {
  std::string config_revision;
  std::string schedule_revision;
  std::string holiday_revision;
  std::vector<Schedule> schedules;
  int32_t holiday_start{0};
  std::vector<uint8_t> days;  // Consecutive days: 0 unknown, 1 workday, 2 holiday.
};

struct Ring {
  bool due{false};
  uint8_t volume{0};
};

// Valid fractional skips cannot equal a schema 2 fixed alarm's whole minute.
// Preserve that distinction instead of truncating fractions and skipping a ring.
constexpr int64_t NON_MINUTE_SKIP = std::numeric_limits<int64_t>::min();

namespace alarm_detail {

inline bool digits(const std::string &value, size_t start, size_t count, int &out) {
  if (start > value.size() || count > value.size() - start)
    return false;
  int parsed = 0;
  for (size_t i = start; i < start + count; ++i) {
    if (value[i] < '0' || value[i] > '9')
      return false;
    parsed = parsed * 10 + value[i] - '0';
  }
  out = parsed;
  return true;
}

// Gregorian civil-date conversion; caller validates the date first.
inline int32_t civil_day(int year, int month, int day) {
  year -= month <= 2;
  const int era = year / 400;
  const int year_of_era = year - era * 400;
  const int day_of_year = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
  const int day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
  return era * 146097 + day_of_era - 719468;
}

inline int64_t floor_div(int64_t value, int64_t divisor) {
  return value / divisor - (value % divisor < 0 ? 1 : 0);
}

inline bool supported_time(int64_t utc) {
  const int64_t first = static_cast<int64_t>(civil_day(1, 1, 1)) * 86400 - 28800;
  const int64_t last = (static_cast<int64_t>(civil_day(9999, 12, 31)) + 1) * 86400 - 28800;
  return utc >= first && utc < last;
}

}  // namespace alarm_detail

inline bool parse_date(const std::string &value, int32_t &out) {
  if (value.size() != 10 || value[4] != '-' || value[7] != '-')
    return false;
  int year, month, day;
  if (!alarm_detail::digits(value, 0, 4, year) || !alarm_detail::digits(value, 5, 2, month) ||
      !alarm_detail::digits(value, 8, 2, day) || year < 1 || month < 1 || month > 12 || day < 1)
    return false;
  constexpr int month_days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  const bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
  if (day > month_days[month - 1] + (month == 2 && leap ? 1 : 0))
    return false;
  out = alarm_detail::civil_day(year, month, day);
  return true;
}

inline bool parse_skip(const std::string &value, int64_t &out) {
  if (value.size() < 25 || value.size() > 32 || value[10] != 'T' || value[13] != ':' ||
      value[16] != ':' || value.compare(value.size() - 6, 6, "+08:00") != 0)
    return false;
  int32_t day;
  int hour, minute, second;
  if (!parse_date(value.substr(0, 10), day) || !alarm_detail::digits(value, 11, 2, hour) ||
      !alarm_detail::digits(value, 14, 2, minute) || !alarm_detail::digits(value, 17, 2, second) ||
      hour > 23 || minute > 59 || second > 59)
    return false;
  const size_t zone = value.size() - 6;
  bool fractional = false;
  if (zone != 19) {
    if (value[19] != '.' || zone < 21 || zone > 26)
      return false;
    for (size_t i = 20; i < zone; ++i) {
      if (value[i] < '0' || value[i] > '9')
        return false;
      fractional = fractional || value[i] != '0';
    }
  }
  out = fractional ? NON_MINUTE_SKIP : static_cast<int64_t>(day) * 86400 + hour * 3600 + minute * 60 +
                                         second - 28800;
  return true;
}

inline bool matches(const Snapshot &snapshot, const Schedule &schedule, int64_t occurrence_utc) {
  if (!schedule.enabled || schedule.minute_of_day >= 1440 || occurrence_utc % 60 != 0 ||
      !alarm_detail::supported_time(occurrence_utc))
    return false;
  const int64_t local = occurrence_utc + 28800;
  const int32_t day = static_cast<int32_t>(alarm_detail::floor_div(local, 86400));
  const int minute = static_cast<int>((local - static_cast<int64_t>(day) * 86400) / 60);
  if (minute != schedule.minute_of_day ||
      std::find(schedule.skipped.begin(), schedule.skipped.end(), occurrence_utc) != schedule.skipped.end())
    return false;
  const int64_t index = static_cast<int64_t>(day) - snapshot.holiday_start;
  const uint8_t kind = index >= 0 && static_cast<uint64_t>(index) < snapshot.days.size()
                           ? snapshot.days[static_cast<size_t>(index)]
                           : 0;
  if (schedule.skip_holidays && kind != 1)
    return false;
  switch (schedule.rule) {
    case Rule::DAILY:
      return true;
    case Rule::WEEKDAYS: {
      // 1970-01-01 was Thursday; normalize modulo for dates before the epoch.
      const int weekday = ((day + 3) % 7 + 7) % 7;
      return (schedule.weekdays & (1U << weekday)) != 0;
    }
    case Rule::DATES:
      return std::find(schedule.dates.begin(), schedule.dates.end(), day) != schedule.dates.end();
    case Rule::WORKDAY:
      return kind == 1;
    case Rule::HOLIDAY:
      return kind == 2;
  }
  return false;
}

inline Ring due(const Snapshot &snapshot, int64_t now, int64_t last_fired) {
  Ring result;
  if (!alarm_detail::supported_time(now))
    return result;
  const int64_t minute = alarm_detail::floor_div(now, 60) * 60;
  // ponytail: aggregate same-minute alarms once; per-alarm playback needs a queue.
  if (now - minute > 5 || last_fired >= minute)
    return result;
  for (const auto &schedule : snapshot.schedules) {
    if (matches(snapshot, schedule, minute)) {
      result.due = true;
      const uint8_t volume = schedule.silent ? 0 : std::min<uint8_t>(schedule.volume, 100);
      result.volume = std::max(result.volume, volume);
    }
  }
  return result;
}

}  // namespace webclock
}  // namespace esphome
