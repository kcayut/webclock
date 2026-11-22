#pragma once
#include <algorithm>
#include <cstdint>

namespace deskclock {
// Values 0..1439 retain the time even while disabled. Add 1440 to enable.
struct Editor {
  enum Field { Clock, Enabled, Hour, Tens, Units } field = Clock;
  int draft = 0;

  void confirm(int &saved) {
    if (field == Clock) draft = valid(saved) ? saved : 420;
    if (field == Units) saved = draft;
    field = static_cast<Field>((field + 1) % 5);
  }
  static bool valid(int value) { return value >= 0 && value < 2880; }
  void select() {
    const int minute = draft % 60;
    switch (field) {
      case Enabled: draft = (draft + 1440) % 2880; break;
      case Hour: draft += 60 * (((draft / 60 + 1) % 24) - (draft / 60 % 24)); break;
      case Tens: draft += 10 * (((minute / 10 + 1) % 6) - minute / 10); break;
      case Units: draft += (minute + 1) % 10 - minute % 10; break;
      case Clock: break;
    }
  }
  void cancel() { field = Clock; }
};

inline Editor editor;

// Ringing uses a deliberate two-step stop: open the prompt, move from Cancel
// to Confirm, then press OK. Cancel closes the prompt and keeps ringing.
struct RingCancel {
  enum Choice { Cancel = 0, Confirm };
  bool open = false;
  Choice choice = Cancel;

  void reset() { open = false; choice = Cancel; }
  void toggle() { choice = choice == Cancel ? Confirm : Cancel; }
};
inline RingCancel ring_cancel;

inline bool due(int saved, int hour, int minute, int second, int stamp, int last_minute) {
  return Editor::valid(saved) && saved == 1440 + hour * 60 + minute &&
         second < 6 && stamp > last_minute;
}
}  // namespace deskclock
