#pragma once

#include "ui_language.h"
#include <cstdint>
#include <string>

namespace deskclock {
// Stored in ESPHome preferences on each desk clock.
struct DisplayPrefs {
  enum TimeStyle : uint8_t { H24, H12, HideTime };
  enum DateStyle : uint8_t { Full, Short, HideDate };
  TimeStyle time_style = H24;
  DateStyle date_style = Full;
  bool alarms = true, reminders = true, calendar = true, battery = true;

  int hour(int h) const { return time_style == H12 ? (h + 11) % 12 + 1 : h; }
  const char *date_pattern() const { return date_style == Short ? "%m / %d" : "%Y / %m / %d"; }
};

struct Menu {
  enum Item { Time, Alarm, Usb, Display, Count };
  enum Screen { Home, List, Preferences };
  enum Option { UiLanguage, TimeFormat, DateFormat, AlarmStatus, Reminders, Calendar, Battery, Environment, OptionCount };

  Screen screen = Home;
  Item item = Time;
  Option option = UiLanguage;
  // The RLCD owns the existing persisted sensor preference.
  bool *environment = nullptr;

  bool active() const { return screen != Home; }
  bool preferences() const { return screen == Preferences; }
  int row_count() const { return preferences() ? (environment ? int(OptionCount) : int(Battery)) : int(Count); }
  int selected() const { return preferences() ? int(option) : int(item); }
  void open() { screen = List; item = Time; }
  void open_preferences() { screen = Preferences; option = UiLanguage; }
  void next() {
    int row = (selected() + 1) % row_count();
    if (preferences()) option = static_cast<Option>(row);
    else item = static_cast<Item>(row);
  }
  void back() { screen = preferences() ? List : Home; }
  void close() { screen = Home; }

  std::string row_label(int row, const DisplayPrefs &p, Language language) const {
    static constexpr Text items[] = {Text::SetTime, Text::DailyAlarm, Text::UsbPair, Text::Display};
    if (!preferences()) return translate(language, items[row]);
    static constexpr Text options[] = {Text::Language, Text::Time, Text::Date, Text::AlarmStatus,
                                       Text::Reminders, Text::Calendar, Text::Battery, Text::Environment};
    std::string label = std::string(translate(language, options[row])) + "  ";
    if (row == UiLanguage) return label + language_name(language);
    Text value = Text::Hidden;
    switch (row) {
      case TimeFormat: value = p.time_style == DisplayPrefs::H24 ? Text::Hours24 : p.time_style == DisplayPrefs::H12 ? Text::Hours12 : Text::Hidden; break;
      case DateFormat: value = p.date_style == DisplayPrefs::Full ? Text::FullDate : p.date_style == DisplayPrefs::Short ? Text::ShortDate : Text::Hidden; break;
      case AlarmStatus: value = p.alarms ? Text::Shown : Text::Hidden; break;
      case Reminders: value = p.reminders ? Text::Shown : Text::Hidden; break;
      case Calendar: value = p.calendar ? Text::Shown : Text::Hidden; break;
      case Battery: value = p.battery ? Text::Shown : Text::Hidden; break;
      case Environment: value = *environment ? Text::Shown : Text::Hidden; break;
    }
    return label + translate(language, value);
  }

  void change(DisplayPrefs &p, Language &language) {
    switch (option) {
      case UiLanguage: language = next_language(language); break;
      case TimeFormat: p.time_style = static_cast<DisplayPrefs::TimeStyle>((p.time_style + 1) % 3); break;
      case DateFormat: p.date_style = static_cast<DisplayPrefs::DateStyle>((p.date_style + 1) % 3); break;
      case AlarmStatus: p.alarms = !p.alarms; break;
      case Reminders: p.reminders = !p.reminders; break;
      case Calendar: p.calendar = !p.calendar; break;
      case Battery: p.battery = !p.battery; break;
      case Environment: *environment = !*environment; break;
      case OptionCount: break;
    }
  }
};

inline Menu menu;
}  // namespace deskclock
