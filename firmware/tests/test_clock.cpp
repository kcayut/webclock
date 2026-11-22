#include "../core/local_alarm.h"
#include "../core/menu.h"
#include "../core/rtc.h"
#include "../views/ticker.h"
#include <cassert>

int main() {
  using namespace deskclock;
  int saved = 1439;
  Editor edit;
  edit.confirm(saved);
  edit.select();            // enable, retain 23:59 until saved
  edit.confirm(saved);
  edit.select();            // 23 -> 0
  edit.confirm(saved);
  edit.select();            // 5 -> 0 tens
  edit.confirm(saved);
  edit.select();            // 9 -> 0 units
  assert(saved == 1439);
  edit.confirm(saved);
  assert(saved == 1440 && edit.field == Editor::Clock);
  edit.confirm(saved);
  edit.select();
  edit.cancel();
  assert(saved == 1440 && edit.field == Editor::Clock);
  assert(due(saved, 0, 0, 5, 100, 99));
  assert(!due(saved, 0, 0, 6, 100, 99));
  assert(!due(saved, 0, 0, 1, 100, 100));
  assert(!due(0, 0, 0, 1, 101, 100));
  assert(due(1441, 0, 1, 0, 101, 100)); // same day, reprogrammed for a later time
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
  nav.next(); assert(nav.item == Menu::Time);
  nav.close();
  assert(!nav.active());

  RingCancel ring;
  assert(!ring.open && ring.choice == RingCancel::Cancel);
  ring.open = true;
  ring.toggle(); assert(ring.choice == RingCancel::Confirm);
  ring.toggle(); assert(ring.choice == RingCancel::Cancel);
  ring.reset();
  assert(!ring.open && ring.choice == RingCancel::Cancel);

  assert(line_width("選單") == 2 * 28);
  assert(line_width("USB 配對") == 6 * 28);
}
