// Run the firmware protocol against the Flask test client over stdin/stdout.
#include "desk_sync.h"
#include <cstdlib>
#include <cassert>
#include <iostream>
using namespace esphome::webclock;

static JsonDocument read_json() {
  std::string line;
  JsonDocument doc;
  if (!std::getline(std::cin, line) || deserializeJson(doc, line)) std::exit(2);
  return doc;
}
static void send(const JsonDocument &doc) {
  serializeJson(doc, std::cout);
  std::cout << std::endl;
}
int main() {
  assert(!subscribe_legacy_schedules(true, false));
  assert(!subscribe_legacy_schedules(true, true));
  assert(!subscribe_legacy_schedules(false, true));
  assert(subscribe_legacy_schedules(false, false));
  const auto input = read_json();
  JsonDocument output;
  if (input["display"].is<JsonObjectConst>()) {
    JsonDocument display(input["display"]);
    DeskTicker ticker;
    const bool scoped = input["scoped"].as<bool>();
    if (input["previous_display"].is<JsonObjectConst>())
      ticker_lines(JsonDocument(input["previous_display"]), scoped, ticker);
    output["ttl"] = ticker_lines(display, scoped, ticker);
    output["line"] = ticker.line(true, true);
    output["reminders"] = ticker.line(true, false);
    output["calendar"] = ticker.line(false, true);
    output["disabled"] = ticker.line(false, false);
  } else {
    DeskAlarm alarm;
    alarm.value = input["value"];
    alarm.base = input["base"];
    alarm.skip = input["skip"] | 0;
    alarm.base_skip = input["base_skip"] | 0;
    alarm.generation = input["generation"] | 0;
    std::string id = input["id"] | "";
    auto http = [](const char *method, const std::string &path, const JsonDocument &body, JsonDocument &reply) {
      JsonDocument request;
      request["method"] = method;
      request["path"] = path;
      request["body"] = body;
      send(request);
      auto response = read_json();
      reply.set(response["body"]);
      return response["status"].as<int>();
    };
    DeskAck ack{alarm, {}};
    int last_minute = input["last_minute"] | 0;
    const bool ok = sync_daily(ack, "wc-001122334455", id, input["now"] | 0, http);
    if (input["while_waiting"].is<int>()) alarm.save(input["while_waiting"].as<int>());
    if (input["skip_while_waiting"].is<int>()) alarm.skip = input["skip_while_waiting"];
    if (ok) apply_ack(alarm, ack, last_minute);
    if (input["save_after"].is<int>()) alarm.save(input["save_after"].as<int>());
    output["ok"] = ok;
    output["last_minute"] = last_minute;
    output["id"] = id;
    output["value"] = alarm.value;
    output["base"] = alarm.base;
    output["base_skip"] = alarm.base_skip;
    output["skip"] = alarm.skip;
    output["generation"] = alarm.generation;
  }
  send(output);
}
