#include "sync_codec.h"
#include <cassert>
#include <fstream>
#include <iostream>

using namespace esphome::webclock;

int main(int argc, char **argv) {
  assert(argc == 2);
  std::ifstream input(argv[1]);
  JsonDocument source;
  assert(!deserializeJson(source, input));
  Snapshot snapshot;
  assert(decode(source.as<JsonObjectConst>(), snapshot));
  assert(snapshot.schedules.size() == 1 && snapshot.days.size() == 1826);
  int64_t monday;
  assert(parse_skip("2026-10-05T07:30:00+08:00", monday));
  assert(due(snapshot, monday, 0).due);
  auto check_bad = [&](auto change) {
    JsonDocument bad(source);
    change(bad);
    Snapshot previous = snapshot;
    assert(!decode(bad.as<JsonObjectConst>(), previous));
    assert(previous.schedule_revision == snapshot.schedule_revision);
    assert(previous.schedules.size() == snapshot.schedules.size());
  };
  check_bad([](JsonDocument &d) { d["config"]["schema_version"] = 3; });
  check_bad([](JsonDocument &d) { d["schedules"]["revision"] = "stale"; });
  check_bad([](JsonDocument &d) { d["holidays"]["days"].remove("2026-10-05"); });
  check_bad([](JsonDocument &d) { d["holidays"]["days"]["2026-10-05"] = false; });
  check_bad([](JsonDocument &d) { d["schedules"]["schedules"][0]["time"] = "7:30"; });
  check_bad([](JsonDocument &d) { d["schedules"]["schedules"][0]["browser_volume"] = "50"; });
  check_bad([](JsonDocument &d) { d["schedules"]["schedules"][0]["browser_volume"] = true; });
  check_bad([](JsonDocument &d) { d["schedules"]["schedules"][0]["enabled"] = 1; });
  check_bad([](JsonDocument &d) { d["schedules"]["schedules"][0]["rule"]["unexpected"] = true; });
  check_bad([](JsonDocument &d) { d["schedules"]["schedules"][0]["calendar_link"]["mode"] = "day"; });
  check_bad([](JsonDocument &d) { d["schedules"]["schedules"][0] = nullptr; });
  check_bad([](JsonDocument &d) {
    auto rows = d["schedules"]["schedules"].as<JsonArray>();
    while (rows.size() <= MAX_SCHEDULES) rows.add(rows[0]);
  });
  JsonDocument empty(source);
  empty["schedules"]["schedules"].to<JsonArray>();
  assert(decode(empty.as<JsonObjectConst>(), snapshot) && snapshot.schedules.empty());
  JsonDocument quiet(source);
  quiet["schedules"]["schedules"][0]["browser_sound"] = "silent";
  assert(decode(quiet.as<JsonObjectConst>(), snapshot));
  assert(due(snapshot, monday, 0).due && due(snapshot, monday, 0).volume == 0);
  quiet["schedules"]["schedules"][0]["type"] = "reminder";
  assert(decode(quiet.as<JsonObjectConst>(), snapshot) && !due(snapshot, monday, 0).due);
  std::cout << "sync codec: server fixture and rejection cases passed\n";
}
