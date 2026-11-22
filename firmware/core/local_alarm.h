#pragma once
#include <algorithm>
#include <cstdint>

namespace deskclock {
// Values 0..1439 retain the time even while disabled. Add 1440 to enable.
struct Editor {
  enum Field { Clock, Enabled, Hour, Tens, Units } field = Clock;
  enum Action { EditTime, Skip, Resume, Disable } action = EditTime;
  int draft = 0, original = 0, original_skip = 0, target = 0;

  static bool valid(int value) { return value >= 0 && value < 2880; }
  void begin(int saved, int skip, int now_minute) {
    original = draft = valid(saved) ? saved : 420;
    original_skip = skip;
    target = 0;
    if (saved >= 1440 && now_minute > 0 && skip != now_minute) {
      // Daily alarms use Taipei civil time (UTC+8).
      const int ahead = (saved % 1440 - (now_minute + 480) % 1440 + 1440) % 1440;
      target = skip >= now_minute ? skip : now_minute + (ahead ? ahead : 1440);
    }
    action = EditTime;
    field = Enabled;
  }
  bool confirm(int &saved, int &skip, int now_minute) {
    if (saved != original || skip != original_skip ||
        ((action == Skip || action == Resume) && (now_minute <= 0 || target <= now_minute))) {
      begin(saved, skip, now_minute);
      return false;
    }
    if (field == Units || action != EditTime) {
      if (action == Skip) skip = target;
      else if (action == Resume || action == Disable || saved != draft) skip = 0;
      saved = action == Disable ? saved % 1440 : draft;
      field = Clock;
      return true;
    }
    field = static_cast<Field>(field + 1);
    return false;
  }
  void select() {
    const int minute = draft % 60;
    switch (field) {
      case Enabled:
        if (original < 1440) draft = (draft + 1440) % 2880;
        else if (action == EditTime && target) action = target == original_skip ? Resume : Skip;
        else action = action == Disable ? EditTime : Disable;
        break;
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

inline bool due(int saved, int hour, int minute, int second, int stamp, int last_minute, int skip = 0) {
  return Editor::valid(saved) && saved == 1440 + hour * 60 + minute &&
         second < 6 && stamp > last_minute && stamp != skip;
}
}  // namespace deskclock
