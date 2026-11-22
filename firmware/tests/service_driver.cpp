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
    std::string line;
    output["ttl"] = calendar_line(display, input["scoped"].as<bool>(), line);
    output["line"] = line;
  } else {
    DeskAlarm alarm;
    alarm.value = input["value"];
    alarm.base = input["base"];
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
    DeskAck ack{alarm, 0};
    const bool ok = sync_daily(alarm, "wc-001122334455", id, http, ack.remote);
    if (input["while_waiting"].is<int>()) alarm.save(input["while_waiting"].as<int>());
    if (ok) apply_ack(alarm, ack);
    if (input["save_after"].is<int>()) alarm.save(input["save_after"].as<int>());
    output["ok"] = ok;
    output["id"] = id;
    output["value"] = alarm.value;
    output["base"] = alarm.base;
    output["generation"] = alarm.generation;
  }
  send(output);
}
