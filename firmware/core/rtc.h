#pragma once
#include <chrono>
#include <cstdint>

namespace deskclock {
// PCF85063A addresses 04h..0Ah form one coherent UTC snapshot.
inline uint8_t bcd(int value) { return (value / 10) * 16 + value % 10; }
inline int decimal(uint8_t value) {
  return (value & 15) <= 9 && (value >> 4) <= 9 ? (value >> 4) * 10 + (value & 15) : -1;
}
inline int64_t rtc_epoch(const uint8_t (&data)[7]) {
  using namespace std::chrono;
  const int s = decimal(data[0]), m = decimal(data[1]), h = decimal(data[2]);
  const int d = decimal(data[3]), mo = decimal(data[5]), y = decimal(data[6]);
  if (s < 0 || s > 59 || m < 0 || m > 59 || h < 0 || h > 23 ||
      d < 1 || mo < 1 || y < 19 || data[4] > 6) return 0;
  const auto date = year(2000 + y) / mo / d;
  if (!date.ok()) return 0;
  return duration_cast<seconds>(sys_days(date).time_since_epoch()).count() + h * 3600 + m * 60 + s;
}

struct ManualClock {
  enum Field { Idle, Year, Month, Day, Hour, Tens, Units } field{Idle};
  int year{2026}, month{1}, day{1}, hour{0}, minute{0};

  int last_day() const {
    using namespace std::chrono;
    return unsigned((std::chrono::year(year) / month / last).day());
  }
  void select() {
    switch (field) {
      case Year: year = year == 2099 ? 2020 : year + 1; break;
      case Month: month = month % 12 + 1; break;
      case Day: day = day % last_day() + 1; break;
      case Hour: hour = (hour + 1) % 24; break;
      case Tens: minute = (minute / 10 + 1) % 6 * 10 + minute % 10; break;
      case Units: minute = minute / 10 * 10 + (minute + 1) % 10; break;
      case Idle: return;
    }
    if (day > last_day()) day = last_day();
  }
  int64_t epoch() const {
    using namespace std::chrono;
    const auto date = std::chrono::year(year) / month / day;
    return duration_cast<seconds>(sys_days(date).time_since_epoch()).count() + (hour - 8) * 3600 + minute * 60;
  }
};
inline ManualClock manual;
}  // namespace deskclock
