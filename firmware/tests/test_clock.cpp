#include "../core/local_alarm.h"
#include "../core/menu.h"
#include "../core/rtc.h"
#include "../views/ticker.h"
#include <cassert>

int main() {
  using namespace deskclock;
  int saved = 1439;
  Editor edit;
  edit.begin(saved, 0, 0);
  int skip = 0;
  edit.select();            // enable, retain 23:59 until saved
  edit.confirm(saved, skip, 0);
  edit.select();            // 23 -> 0
  edit.confirm(saved, skip, 0);
  edit.select();            // 5 -> 0 tens
  edit.confirm(saved, skip, 0);
  edit.select();            // 9 -> 0 units
  assert(saved == 1439);
  edit.confirm(saved, skip, 0);
  assert(saved == 1440 && edit.field == Editor::Clock);
  edit.begin(saved, skip, 0);
  edit.select();
  edit.cancel();
  assert(saved == 1440 && edit.field == Editor::Clock);
  assert(due(saved, 0, 0, 5, 100, 99));
  assert(!due(saved, 0, 0, 6, 100, 99));
  assert(!due(saved, 0, 0, 1, 100, 100));
  assert(!due(0, 0, 0, 1, 101, 100));
  assert(due(1441, 0, 1, 0, 101, 100)); // same day, reprogrammed for a later time
  saved = 1440; // midnight Taipei
  const int midnight = 1440 * 20000 - 480;
  edit.begin(saved, skip, midnight - 1);
  edit.select();
  assert(edit.action == Editor::Skip && edit.target == midnight);
  assert(edit.confirm(saved, skip, midnight - 1) && skip == midnight && saved == 1440);
  assert(!due(saved, 0, 0, 0, midnight, 0, skip));
  assert(due(saved, 0, 0, 0, midnight + 1440, 0, skip));
  edit.begin(saved, skip, midnight - 1);
  edit.select();
  assert(edit.action == Editor::Resume && edit.confirm(saved, skip, midnight - 1) && skip == 0);
  edit.begin(saved, skip, midnight - 1);
  edit.select();
  assert(!edit.confirm(saved, skip, midnight) && skip == 0); // expired preview
  edit.select();
  assert(edit.target == midnight + 1440);
  edit.select();
  assert(edit.action == Editor::Disable && edit.confirm(saved, skip, midnight) && saved == 0);
  saved = 1500;
  edit.begin(saved, 0, 0); // no clock: can cancel, cannot choose a date
  edit.select();
  assert(edit.action == Editor::Disable && edit.confirm(saved, skip, 0) && saved == 60);
  uint8_t date[] = {0, 0, 0, bcd(22), 0, bcd(11), bcd(26)};
  assert(rtc_epoch(date) == 1795305600); // Sunday, UTC
  date[0] = 0x80;                         // oscillator-stop flag
  assert(rtc_epoch(date) == 0);
  date[0] = 0x1a;
  assert(rtc_epoch(date) == 0);
  date[0] = 0;
  date[3] = bcd(29);
  date[5] = bcd(2);
  assert(rtc_epoch(date) == 0);
  date[6] = bcd(28);
  assert(rtc_epoch(date) > 0);

  ManualClock c{ManualClock::Year, 2028, 2, 29, 8, 0};
  c.select();
  assert(c.year == 2029 && c.day == 28);
  c = {ManualClock::Year, 2099, 12, 31, 23, 59};
  c.select();
  assert(c.year == 2020);
  c.field = ManualClock::Day; c.select();
  assert(c.day == 1);
  c = {ManualClock::Month, 2026, 1, 31, 8, 0};
  c.select();
  assert(c.month == 2 && c.day == 28);
  c = {ManualClock::Units, 2026, 11, 22, 8, 9};
  c.select();
  assert(c.minute == 0 && c.epoch() == 1795305600);

  assert(tile_index(U'●') != tile_index('?') && tile_index(U'×') != tile_index('?'));
  Ticker t;
  t.reset(1000);
  assert(!t.advance("早安", 9000));
  std::string message;
  for (int i = 0; i < 30; ++i) message += "鐘";
  assert(!t.advance(message, 16999));
  assert(t.advance(message, 17000) && t.start == 24);
  assert(t.advance(message, 25000) && t.start == 0);
  size_t pos = 0;
  assert(next_char(message, pos) == U'鐘' && pos == 3);
  assert(tile_index(U'鐘') != tile_index('?') && tile_index(0x1f4cc) == tile_index('?'));

  Menu nav;
  assert(!nav.active() && nav.item == Menu::Time);
  nav.open();
  assert(nav.active() && nav.item == Menu::Time);
  nav.next(); assert(nav.item == Menu::Alarm);
  nav.next(); assert(nav.item == Menu::Usb);
  nav.next(); assert(nav.item == Menu::Display);
  DisplayPrefs prefs;
  assert(prefs.hour(0) == 0 && prefs.alarms && prefs.reminders && prefs.calendar);
  static_assert(sizeof(DisplayPrefs) == 6, "Preserve existing display preferences on firmware updates");
  Language lang{};
  assert(lang == Language::English && nav.row_label(nav.selected(), prefs, lang) == "Display settings");
  nav.open_preferences();
  assert(nav.row_count() == 6 && nav.selected() == 0);
  assert(nav.row_label(0, prefs, lang) == "Language  English");
  nav.change(prefs, lang); assert(nav.row_label(0, prefs, lang) == "語言  繁體中文");
  nav.change(prefs, lang); assert(nav.row_label(0, prefs, lang) == "言語  日本語");
  nav.change(prefs, lang); assert(lang == Language::English);
  nav.next();
  nav.change(prefs, lang);
  assert(prefs.hour(0) == 12 && prefs.hour(12) == 12 && prefs.hour(13) == 1);
  nav.change(prefs, lang); assert(prefs.time_style == DisplayPrefs::HideTime);
  nav.change(prefs, lang); assert(prefs.time_style == DisplayPrefs::H24);
  nav.next(); nav.change(prefs, lang); assert(prefs.date_style == DisplayPrefs::Short);
  nav.change(prefs, lang); assert(prefs.date_style == DisplayPrefs::HideDate);
  nav.next(); nav.change(prefs, lang); assert(!prefs.alarms);
  nav.next(); nav.change(prefs, lang); assert(!prefs.reminders && prefs.calendar);
  nav.next(); nav.change(prefs, lang); assert(!prefs.calendar);
  nav.next(); assert(nav.selected() == 0);
  bool environment = false;
  nav.environment = &environment;
  assert(nav.row_count() == 8);
  for (int i = 0; i < 6; ++i) nav.next();
  nav.change(prefs, lang); assert(!prefs.battery);
  nav.next(); assert(nav.row_label(nav.selected(), prefs, Language::TraditionalChinese) == "溫濕度  隱藏");
  nav.change(prefs, lang); assert(environment);
  nav.back(); assert(!nav.preferences() && nav.item == Menu::Display);
  nav.next(); assert(nav.item == Menu::Time);
  nav.back(); assert(!nav.active());

  RingCancel ring;
  assert(!ring.open && ring.choice == RingCancel::Cancel);
  ring.open = true;
  ring.toggle(); assert(ring.choice == RingCancel::Confirm);
  ring.toggle(); assert(ring.choice == RingCancel::Cancel);
  ring.reset();
  assert(!ring.open && ring.choice == RingCancel::Cancel);

  assert(line_width("跳過下一次 11/23 07:30") < 560);
  assert(line_width("恢復響鈴 11/23 07:30") < 560);
  // Both panels use the same 14x16 atlas, at native or double pixel size.
  struct Atlas {
    struct Pixel { bool is_on() const { return true; } };
    Pixel get_pixel(int, int) const { return {}; }
  } atlas;
  struct Screen {
    int scale, pixels = 0;
    void filled_rectangle(int x, int y, int w, int h, int) {
      assert(w == scale && h == scale);
      assert(x >= 0 && x + w <= scale * 28 && y >= 0 && y + h <= scale * 16);
      pixels += w * h;
    }
  };
  for (int scale : {1, 2}) {
    Screen screen{scale};
    draw_line(screen, atlas, "鬧鐘", 0, 0, 1, 0, scale);
    assert(screen.pixels == 2 * 14 * 16 * scale * scale);
  }
  assert(line_width("選單") == 2 * 28);
  assert(line_width("USB 配對") == 6 * 28);
}
