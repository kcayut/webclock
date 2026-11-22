#pragma once

namespace deskclock {
// One menu layer shared by every enclosure. Sub-screens stay represented by
// Editor::field, ManualClock::field and deskusb::active(); the menu remains
// open underneath them so Cancel returns one level instead of all the way home.
struct Menu {
  enum Item { Time = 0, Alarm, Usb, Count };
  enum Screen { Home, List };

  Screen screen = Home;
  Item item = Time;

  bool active() const { return screen == List; }
  void open() { screen = List; item = Time; }
  void next() { item = static_cast<Item>((item + 1) % Count); }
  void close() { screen = Home; }
};

inline Menu menu;
}  // namespace deskclock
