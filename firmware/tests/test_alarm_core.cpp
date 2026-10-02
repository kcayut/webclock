#include "../components/webclock/alarm_core.h"

#include <cassert>
#include <iostream>

using namespace esphome::webclock;

static int32_t day(const std::string &value) {
  int32_t result;
  assert(parse_date(value, result));
  return result;
}

static int64_t stamp(const std::string &value) {
  int64_t result;
  assert(parse_skip(value, result));
  return result;
}

int main() {
  assert(day("1970-01-01") == 0);
  assert(day("1969-12-31") == -1);
  assert(day("2000-03-01") - day("2000-02-28") == 2);
  assert(day("1900-03-01") - day("1900-02-28") == 1);
  assert(day("0001-01-01") == -719162);
  assert(day("9999-12-31") == 2932896);
  int32_t parsed_day = 42;
  for (const auto *bad : {"0000-01-01", "1900-02-29", "2026-02-29", "2026-04-31", "2026-13-01",
                          "2026-00-01", "2026-01-00", "2026-1-01", "2026-01-01x", "202a-01-01"}) {
    assert(!parse_date(bad, parsed_day));
    assert(parsed_day == 42);
  }
  const int64_t monday = stamp("2026-10-05T00:00:00+08:00");
  assert(monday == static_cast<int64_t>(day("2026-10-04")) * 86400 + 16 * 3600);
  assert(stamp("2026-10-05T00:00:00.000000+08:00") == monday);
  assert(stamp("2026-10-05T00:00:00.001+08:00") == NON_MINUTE_SKIP);
  assert(stamp("2026-10-04T23:59:59.999999+08:00") == NON_MINUTE_SKIP);
  assert(stamp("2026-10-05T00:00:01+08:00") == monday + 1);
  int64_t parsed_stamp = 42;
  for (const auto *bad : {"2026-10-05T00:00:00Z", "2026-10-05T00:00:00+00:00", "2026-10-05T00:00:00",
                          "2026-10-05T00:00:00.+08:00", "2026-10-05T00:00:00.0000001+08:00",
                          "2026-10-05T00:00:00.a+08:00", "2026-10-05 00:00:00+08:00",
                          "2026-10-05T24:00:00+08:00", "2026-10-05T00:60:00+08:00",
                          "2026-10-05T00:00:60+08:00", "2026-02-29T00:00:00+08:00"}) {
    assert(!parse_skip(bad, parsed_stamp));
    assert(parsed_stamp == 42);
  }

  Snapshot snapshot;
  snapshot.holiday_start = day("2026-10-03");
  snapshot.days = {1, 2, 1, 0};  // Saturday workday, Sunday holiday, Monday workday, unknown Tuesday.
  Schedule schedule;
  schedule.id = "wake";
  schedule.rule = Rule::WEEKDAYS;
  schedule.weekdays = 1;  // Monday only, despite Sunday in UTC.
  assert(matches(snapshot, schedule, monday));
  assert(!matches(snapshot, schedule, monday - 86400));
  assert(!matches(snapshot, schedule, monday + 60));
  assert(!matches(snapshot, schedule, monday + 1));
  schedule.weekdays = 1 << 6;
  assert(matches(snapshot, schedule, monday - 86400));
  schedule.weekdays = 1 << 3;
  assert(matches(snapshot, schedule, stamp("1970-01-01T00:00:00+08:00")));
  schedule.weekdays = 1 << 2;
  assert(matches(snapshot, schedule, stamp("1969-12-31T00:00:00+08:00")));

  schedule.rule = Rule::WORKDAY;
  assert(matches(snapshot, schedule, monday - 2 * 86400));  // No weekend guessing.
  assert(!matches(snapshot, schedule, monday - 86400));
  assert(!matches(snapshot, schedule, monday + 86400));
  assert(!matches(snapshot, schedule, monday + 2 * 86400));
  schedule.rule = Rule::HOLIDAY;
  assert(matches(snapshot, schedule, monday - 86400));
  assert(!matches(snapshot, schedule, monday));
  assert(!matches(snapshot, schedule, monday + 86400));
  schedule.rule = Rule::DAILY;
  assert(matches(snapshot, schedule, monday + 2 * 86400));
  schedule.skip_holidays = true;
  assert(matches(snapshot, schedule, monday));
  assert(!matches(snapshot, schedule, monday - 86400));
  assert(!matches(snapshot, schedule, monday + 86400));
  schedule.rule = Rule::DATES;
  schedule.dates = {day("2026-10-05"), day("2026-10-06")};
  assert(matches(snapshot, schedule, monday));
  assert(!matches(snapshot, schedule, monday + 86400));
  schedule.skip_holidays = false;
  assert(matches(snapshot, schedule, monday + 86400));
  assert(!matches(snapshot, schedule, monday + 2 * 86400));
  schedule.skipped = {NON_MINUTE_SKIP, monday + 1};
  assert(matches(snapshot, schedule, monday));
  schedule.skipped.push_back(monday);
  assert(!matches(snapshot, schedule, monday));
  schedule.skipped.clear();
  schedule.enabled = false;
  assert(!matches(snapshot, schedule, monday));
  schedule.enabled = true;
  schedule.minute_of_day = 1440;
  assert(!matches(snapshot, schedule, monday));
  schedule.minute_of_day = 0;

  snapshot.schedules = {schedule};
  Ring ring = due(snapshot, monday, monday - 60);
  assert(ring.due && ring.volume == 100);
  assert(due(snapshot, monday + 5, monday - 60).due);
  assert(!due(snapshot, monday + 6, monday - 60).due);
  assert(!due(snapshot, monday, monday).due);
  assert(!due(snapshot, monday, monday + 86400).due);  // Clock rollback must not replay.
  snapshot.schedules[0].volume = 0;
  ring = due(snapshot, monday, monday - 60);
  assert(ring.due && ring.volume == 0);
  snapshot.schedules[0].volume = 100;
  snapshot.schedules[0].silent = true;
  ring = due(snapshot, monday, monday - 60);
  assert(ring.due && ring.volume == 0);
  schedule.volume = 35;
  snapshot.schedules.push_back(schedule);
  schedule.volume = 70;
  snapshot.schedules.push_back(schedule);
  ring = due(snapshot, monday, monday - 60);
  assert(ring.due && ring.volume == 70);
  assert(!due(snapshot, std::numeric_limits<int64_t>::min(), 0).due);
  assert(!due(snapshot, std::numeric_limits<int64_t>::max(), 0).due);
  assert(!matches(snapshot, schedule, NON_MINUTE_SKIP));
  snapshot.schedules.clear();
  assert(!due(snapshot, monday, monday - 60).due);
  std::cout << "alarm_core checks passed\n";
}
