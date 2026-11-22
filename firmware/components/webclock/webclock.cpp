#include "webclock.h"
#include "sync_codec.h"
#include "esphome/components/json/json_util.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include <esp_crt_bundle.h>
#include <esp_heap_caps.h>
#include <esp_http_client.h>
#include <esp_random.h>
#include <esp_wifi.h>
#include <mbedtls/sha256.h>
#include <nvs.h>
#include <nvs_flash.h>
#include <algorithm>
#include <cstring>
#include <set>

namespace esphome::webclock {
static const char *const TAG = "webclock";
static constexpr size_t MAX_RESPONSE = 192 * 1024;
static constexpr size_t MAX_CACHE = 224 * 1024;
static constexpr uint32_t RING_MS = 60000;

namespace {
struct FreeBuffer { void operator()(uint8_t *p) const { free(p); } };
using Buffer = std::unique_ptr<uint8_t, FreeBuffer>;
Buffer buffer(size_t size) {
  return Buffer(static_cast<uint8_t *>(heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)));
}
struct Response {
  Buffer body{buffer(MAX_RESPONSE)};
  size_t length{0};
  int status{0};
  bool overflow{false};
  std::string etag, content_type;
};
esp_err_t receive(esp_http_client_event_t *event) {
  auto &r = *static_cast<Response *>(event->user_data);
  if (event->event_id == HTTP_EVENT_ON_HEADER) {
    if (strcasecmp(event->header_key, "ETag") == 0) r.etag = event->header_value;
    if (strcasecmp(event->header_key, "Content-Type") == 0) r.content_type = event->header_value;
  }
  if (event->event_id == HTTP_EVENT_ON_DATA && event->data_len > 0) {
    const size_t length = static_cast<size_t>(event->data_len);
    if (length > MAX_RESPONSE - r.length) { r.overflow = true; return ESP_FAIL; }
    std::memcpy(r.body.get() + r.length, event->data, length);
    r.length += length;
  }
  return ESP_OK;
}
Response request(const std::string &url, const std::string &token,
                 const std::string &body = "", const std::string &etag = "",
                 esp_http_client_method_t method = HTTP_METHOD_POST) {
  Response response;
  if (!response.body) return response;
  esp_http_client_config_t config{};
  config.url = url.c_str();
  config.timeout_ms = 5000;
  config.event_handler = receive;
  config.user_data = &response;
  config.disable_auto_redirect = true;  // Never forward the token to a redirect target.
  config.crt_bundle_attach = esp_crt_bundle_attach;
  auto client = esp_http_client_init(&config);
  if (!client) return response;
  const std::string authorization = "Bearer " + token;
  if (!token.empty()) esp_http_client_set_header(client, "Authorization", authorization.c_str());
  esp_http_client_set_header(client, "Accept", "application/json");
  if (!etag.empty()) esp_http_client_set_header(client, "If-None-Match", etag.c_str());
  if (!body.empty()) {
    esp_http_client_set_method(client, method);
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, body.data(), body.size());
  }
  const auto error = esp_http_client_perform(client);
  const int status = esp_http_client_get_status_code(client);
  if (error == ESP_OK && !response.overflow &&
      (status == 304 || esp_http_client_is_complete_data_received(client))) response.status = status;
  esp_http_client_cleanup(client);
  return response;
}
JsonDocument parse(const Response &r) {
  if (r.content_type.find("application/json") == std::string::npos) return JsonDocument();
  return json::parse_json(r.body.get(), r.length);
}
JsonDocument empty_json() {
  return json::parse_json(reinterpret_cast<const uint8_t *>("{}"), 2);
}
bool open_store(nvs_handle_t &handle) { return nvs_open_from_partition("webclock", "clock", NVS_READWRITE, &handle) == ESP_OK; }
bool revoked(bool &value, bool write = false) {
  nvs_handle_t handle;
  if (!open_store(handle)) return false;
  uint8_t flag = value;
  auto error = write ? nvs_set_u8(handle, "revoked", flag) : nvs_get_u8(handle, "revoked", &flag);
  if (!write && error == ESP_ERR_NVS_NOT_FOUND) { flag = 0; error = ESP_OK; }
  if (write && error == ESP_OK) error = nvs_commit(handle);
  nvs_close(handle);
  value = flag;
  return error == ESP_OK;
}
JsonDocument load_bundle() {
  nvs_handle_t handle;
  if (!open_store(handle)) return empty_json();
  size_t size = 0;
  auto error = nvs_get_blob(handle, "snapshot", nullptr, &size);
  Buffer data;
  if (error == ESP_OK && size > 0 && size <= MAX_CACHE) {
    data = buffer(size);
    if (data) error = nvs_get_blob(handle, "snapshot", data.get(), &size);
  }
  nvs_close(handle);
  return error == ESP_OK && data ? json::parse_json(data.get(), size) : empty_json();
}
bool save_bundle(const JsonDocument &bundle) {
  const size_t size = measureJson(bundle);
  if (size == 0 || size > MAX_CACHE || bundle.overflowed()) return false;
  auto data = buffer(size + 1);
  if (!data || serializeJson(bundle, data.get(), size + 1) != size) return false;
  nvs_handle_t handle;
  if (!open_store(handle)) return false;
  auto error = nvs_set_blob(handle, "snapshot", data.get(), size);
  if (error == ESP_OK) error = nvs_commit(handle);
  nvs_close(handle);
  return error == ESP_OK;
}
std::string fingerprint(const std::string &url, const std::string &token) {
  const std::string value = url + "\n" + token;
  unsigned char digest[32];
  mbedtls_sha256(reinterpret_cast<const unsigned char *>(value.data()), value.size(), digest, 0);
  static constexpr char HEX[] = "0123456789abcdef";
  std::string result;
  for (uint8_t byte : digest) { result += HEX[byte >> 4]; result += HEX[byte & 15]; }
  return result;
}
}  // namespace

void WebClock::setup() {
  if (server_url_.empty()) return;
  device_id_ = "wc-" + get_mac_address();
  scope_ = fingerprint(server_url_, api_token_);
  storage_ready_ = nvs_flash_init_partition("webclock") == ESP_OK;
  if (!storage_ready_) ESP_LOGE(TAG, "Cache partition unavailable; alarms disabled until storage is repaired");
  nvs_handle_t handle;
  if (storage_ready_ && open_store(handle)) {
    const auto error = nvs_get_i64(handle, "last_fired", &last_fired_);
    if (error != ESP_OK && error != ESP_ERR_NVS_NOT_FOUND) {
      storage_ready_ = false;
      ESP_LOGE(TAG, "Cannot read alarm deduplication marker; alarms disabled");
    }
    nvs_close(handle);
  }
#ifdef USE_WEBCLOCK_DESK
  binding_ = strtoull(fingerprint(server_url_, control_token_).substr(0, 16).c_str(), nullptr, 16);
  desk_out_ = xQueueCreate(1, sizeof(DeskAlarm));
  desk_in_ = xQueueCreate(1, sizeof(DeskAck));
  ticker_in_ = xQueueCreate(1, sizeof(TickerUpdate));
#endif
  updates_ = xQueueCreate(1, sizeof(Update));
  applied_ = xQueueCreate(1, sizeof(bool));
  if (!updates_ || !applied_ || xTaskCreate(task_entry_, "webclock_sync", 16384, this, 1, nullptr) != pdPASS) {
    ESP_LOGE(TAG, "Cannot start sync worker");
    return;
  }
}
void WebClock::dump_config() {
  ESP_LOGCONFIG(TAG, "WebClock 0.1.0 / schema 2 / maximum 64 records");
  ESP_LOGCONFIG(TAG, "Device ID: %s", device_id_.c_str());
}
void WebClock::task_entry_(void *arg) { static_cast<WebClock *>(arg)->sync_task_(); vTaskDelete(nullptr); }
void WebClock::publish_(const Snapshot *snapshot, bool authorized) {
  Update update{snapshot ? new Snapshot(*snapshot) : nullptr, authorized};
#ifdef USE_WEBCLOCK_DESK
  if (update.snapshot && !mirror_id_.empty()) {
    auto &rows = update.snapshot->schedules;
    rows.erase(std::remove_if(rows.begin(), rows.end(), [&](const Schedule &row) {
      return row.id == mirror_id_;
    }), rows.end());
  }
#endif
  xQueueSend(updates_, &update, portMAX_DELAY);
  bool applied;
  xQueueReceive(applied_, &applied, portMAX_DELAY);  // ACK only after the main loop activates it.
}
bool WebClock::record_fire_(int64_t stamp) {
  nvs_handle_t handle;
  if (!storage_ready_ || !open_store(handle)) return false;
  auto error = nvs_set_i64(handle, "last_fired", stamp);
  if (error == ESP_OK) error = nvs_commit(handle);
  nvs_close(handle);
  return error == ESP_OK;
}
void WebClock::stop() { ringing_ = false; if (buzzer_) buzzer_->set_level(0); output_level_ = 0; }
void WebClock::loop() {
  Update update;
  if (updates_ && xQueueReceive(updates_, &update, 0) == pdTRUE) {
    snapshot_.reset(update.snapshot);
    authorized_ = update.authorized;
    if (ringing_) {
      const auto current = snapshot_ ? due(*snapshot_, last_fired_, last_fired_ - 60) : Ring{};
      if (!authorized_ || !current.due) stop();
      else ring_level_ = volume_limit_ * current.volume / 100.0f;
    }
    const bool applied = true;
    xQueueSend(applied_, &applied, 0);
  }
  const auto now = clock_->utcnow();
  if (authorized_ && snapshot_ && now.is_valid()) {
    const auto ring = due(*snapshot_, now.timestamp, last_fired_);
    if (ring.due) {
      const int64_t stamp = static_cast<int64_t>(now.timestamp) / 60 * 60;
      if (record_fire_(stamp)) {
        last_fired_ = stamp;
        ringing_ = true;
        ring_started_ = millis();
        ring_level_ = volume_limit_ * ring.volume / 100.0f;
        ESP_LOGI(TAG, "Alarm started; stop button or 60-second timeout");
      } else {
        last_fired_ = stamp;  // Avoid retrying a failed flash write on every loop iteration.
        ESP_LOGE(TAG, "Cannot persist alarm deduplication marker; occurrence not played");
      }
    }
  }
  if (ringing_ && millis() - ring_started_ >= RING_MS) stop();
  const float level = ringing_ && (millis() - ring_started_) % 1000 < 350 ? ring_level_ : 0;
  if (level != output_level_) { buzzer_->set_level(level); output_level_ = level; }
}

#ifdef USE_WEBCLOCK_DESK
bool WebClock::desk_tick(DeskAlarm &state, int legacy_value, int &last_minute) {
  if (state.value < 0 || state.value >= 2880)
    state.value = legacy_value >= 0 && legacy_value < 2880 ? legacy_value : 420;
  if (!control_token_.empty() && binding_ && state.binding != binding_) {
    state.binding = binding_;
    state.base = -1;
    state.generation = 0;
    state.base_skip = 0;
  }
  const int before = state.value, previous_base = state.base, previous_skip = state.skip;
  DeskAck ack;
  if (desk_in_ && xQueueReceive(desk_in_, &ack, 0)) apply_ack(state, ack, last_minute);
  if (desk_out_) xQueueOverwrite(desk_out_, &state);
  TickerUpdate incoming;
  if (ticker_in_ && xQueueReceive(ticker_in_, &incoming, 0)) {
    std::unique_ptr<std::string> line(incoming.line);
    ticker_deadline_ = incoming.deadline;
    if (int32_t(millis() - ticker_deadline_) >= 0) line->clear();
    if (ticker_ != *line) { ticker_.swap(*line); return true; }
  }
  if (!ticker_.empty() && int32_t(millis() - ticker_deadline_) >= 0) {
    ticker_.clear();
    return true;
  }
  return before != state.value || previous_base != state.base || previous_skip != state.skip;
}

void WebClock::sync_desk_() {
  DeskAlarm state;
  if (!control_token_.empty() && desk_out_ && desk_in_ && xQueuePeek(desk_out_, &state, 0)) {
    if (state.generation != mirror_generation_) {
      mirror_generation_ = state.generation;
      mirror_id_.clear();
    }
    auto call = [&](const char *method, const std::string &path, const JsonDocument &data, JsonDocument &doc) {
      std::string body;
      if (strcmp(method, "GET") != 0) serializeJson(data, body);
      auto response = request(server_url_ + "/api/v1/control" + path, control_token_, body, "",
                              strcmp(method, "PATCH") == 0 ? HTTP_METHOD_PATCH : HTTP_METHOD_POST);
      doc = parse(response);
      return response.status;
    };
    DeskAck ack{state, {}};
    const auto now = clock_->utcnow();
    if (sync_daily(ack, device_id_, mirror_id_, now.is_valid() ? now.timestamp / 60 : 0, call)) xQueueOverwrite(desk_in_, &ack);
  }
  if (!ticker_in_) return;
  const bool managed = !display_token_.empty();
  const uint32_t started = millis();
  auto response = request(server_url_ + (managed ? "/api/v2/device/display" : "/api/status"), display_token_);
  auto doc = parse(response);
  auto line = std::make_unique<std::string>();
  uint32_t lifetime = 0;
  if (response.status == 200) lifetime = calendar_line(doc, managed, *line);
  TickerUpdate update{line.get(), started + lifetime};
  if (xQueueSend(ticker_in_, &update, pdMS_TO_TICKS(100))) line.release();
}
#endif

void WebClock::sync_task_() {
  auto bundle = load_bundle();
  Snapshot saved;
  bool blocked = true;
  const bool known_revocation = storage_ready_ && revoked(blocked);
  bool have = known_revocation && !blocked && bundle["scope"].as<std::string>() == scope_ && decode(bundle.as<JsonObjectConst>(), saved);
  // Boot must contact this server before enabling cached alarms. This also
  // prevents failed revocation-marker writes from reviving old data on reboot.
  if (!have) bundle = empty_json();
  bool registered = false, force = true, active = false;
  std::string config_etag;
  std::vector<std::string> pending;
  uint32_t retry_ms = 5000;
  auto call = [&](const char *path, const std::string &body = "", const std::string &etag = "") {
    return request(server_url_ + "/api/v1/device/" + path, api_token_, body, etag);
  };
  auto revoke = [&]() {
    bool flag = true;
    if (!revoked(flag, true)) ESP_LOGE(TAG, "Cannot persist authentication failure");
    publish_(nullptr, false);
    have = false;
    active = false;
    bundle = empty_json();
    config_etag.clear();
    pending.clear();
    registered = false;
    ESP_LOGW(TAG, "Authentication refused; cached alarms disabled");
  };
  while (true) {
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK || !storage_ready_) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
#ifdef USE_WEBCLOCK_DESK
    sync_desk_();
    if (!subscribe_legacy_schedules(usb_desk_only_, !display_token_.empty())) { vTaskDelay(pdMS_TO_TICKS(30000)); continue; }
#endif
    bool ok = false, denied = false, synced = false;
    if (!registered) {
      std::string payload = json::build_json([&](JsonObject root) { root["id"] = device_id_; root["name"] = device_name_; });
      auto response = call("register", payload);
      registered = response.status == 201;
      denied = response.status == 401 || response.status == 403;
    }
    if (registered && !denied) {
      auto response = call("config", "", have && !force ? config_etag : "");
      denied = response.status == 401 || response.status == 403;
      if (response.status == 304 && have && active) { ok = synced = true; }
      else if (response.status == 200) {
        auto config = parse(response);
        if (valid_config(config.as<JsonObjectConst>())) {
          auto candidate = empty_json();
          candidate["scope"] = scope_;
          candidate["config"].set(config.as<JsonObjectConst>());
          bool downloaded = true;
          for (const char *resource : {"schedules", "holidays"}) {
            const char *field = strcmp(resource, "schedules") == 0 ? "schedule_revision" : "holiday_revision";
            if (have && bundle[resource]["revision"].as<std::string>() == config[field].as<std::string>()) {
              candidate[resource].set(bundle[resource]);
              continue;
            }
            auto data = call(resource);
            denied = data.status == 401 || data.status == 403;
            if (data.status != 200) { downloaded = false; break; }
            auto document = parse(data);
            if (document.isNull() || document.overflowed() || document["revision"].as<std::string>() != config[field].as<std::string>()) { downloaded = false; break; }
            candidate[resource].set(document.as<JsonObjectConst>());
          }
          Snapshot next;
          if (downloaded && !candidate.overflowed() && decode(candidate.as<JsonObjectConst>(), next)) {
            auto final_response = call("config");
            denied = final_response.status == 401 || final_response.status == 403;
            auto final_config = parse(final_response);
            if (final_response.status == 200 && same_config(config.as<JsonObjectConst>(), final_config.as<JsonObjectConst>())) {
              const bool changed = !have || !same_config(bundle["config"].as<JsonObjectConst>(), config.as<JsonObjectConst>());
              if (!changed || save_bundle(candidate)) {
                bool flag = false;
                if (revoked(flag, true)) {
                  saved = std::move(next);
                  bundle = std::move(candidate);
                  if (changed || !active) publish_(&saved, true);
                  active = true;
                  have = ok = synced = true;
                  config_etag = final_response.etag;
                  ESP_LOGD(TAG, "Synchronized %u records", static_cast<unsigned>(saved.schedules.size()));
                }
              }
            }
          }
        }
      }
      if (!denied) {
        std::string payload = json::build_json([&](JsonObject root) {
          root["id"] = device_id_;
#ifdef CONFIG_IDF_TARGET_ESP32S3
          root["firmware"] = "0.1.0-s3";
#else
          root["firmware"] = "0.1.0-" CONFIG_IDF_TARGET;
#endif
          if (have && active) {
            root["config_revision"] = saved.config_revision;
            root["schedule_revision"] = saved.schedule_revision;
            root["holiday_revision"] = saved.holiday_revision;
          }
          if (synced) { auto acks = root["acknowledged_commands"].to<JsonArray>(); for (const auto &id : pending) acks.add(id); }
        });
        auto status = call("status", payload);
        denied = status.status == 401 || status.status == 403;
        if (status.status == 404) registered = false;
        auto report = parse(status);
        if (status.status == 200 && report["commands"].is<JsonArray>()) {
          std::vector<std::string> commands;
          for (JsonObjectConst command : report["commands"].as<JsonArrayConst>()) {
            if (command["action"].as<std::string>() == "sync" && identifier(command["id"], 64)) commands.push_back(command["id"].as<std::string>());
          }
          if (commands.size() <= 100) pending = std::move(commands);
        } else ok = false;
      }
    }
    if (denied) revoke();
    force = !pending.empty() || !have;
    if (ok && !denied) retry_ms = 5000;
    else { ESP_LOGW(TAG, "Sync incomplete; retaining the previous valid snapshot where authorized"); retry_ms = std::min(retry_ms * 2, uint32_t(300000)); }
    uint32_t delay_ms = ok && !denied ? (force ? 1000 : 30000) : retry_ms;
#ifdef USE_WEBCLOCK_DESK
    delay_ms = std::min(delay_ms, uint32_t(30000));
#endif
    vTaskDelay(pdMS_TO_TICKS(delay_ms + (esp_random() % 1000)));
  }
}

namespace {
// Original seven-segment drawing: no remote font downloads or font redistribution.
void digit(display::Display &d, int value, int x, int y, int w, int h, int t) {
  static constexpr uint8_t SEG[] = {0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f};
  const uint8_t mask = value >= 0 && value <= 9 ? SEG[value] : 0x40;
  const int half = h / 2;
  if (mask & 1) d.filled_rectangle(x+t,y,w-2*t,t);
  if (mask & 2) d.filled_rectangle(x+w-t,y+t,t,half-t);
  if (mask & 4) d.filled_rectangle(x+w-t,y+half,t,half-t);
  if (mask & 8) d.filled_rectangle(x+t,y+h-t,w-2*t,t);
  if (mask & 16) d.filled_rectangle(x,y+half,t,half-t);
  if (mask & 32) d.filled_rectangle(x,y+t,t,half-t);
  if (mask & 64) d.filled_rectangle(x+t,y+half-t/2,w-2*t,t);
}
}
void WebClock::draw(display::Display &screen) {
  const auto now = clock_->now();
  const bool valid = now.is_valid();
  const int values[] = {valid ? now.hour/10 : -1,valid ? now.hour%10 : -1,valid ? now.minute/10 : -1,valid ? now.minute%10 : -1};
  const int positions[] = {8,33,72,97};
  for (int i=0;i<4;i++) digit(screen,values[i],positions[i],5,22,38,3);
  screen.filled_rectangle(61,16,4,4);
  screen.filled_rectangle(61,30,4,4);
  if (valid) {
    int date[] = {now.year/1000,(now.year/100)%10,(now.year/10)%10,now.year%10,now.month/10,now.month%10,now.day_of_month/10,now.day_of_month%10};
    for (int i=0;i<8;i++) digit(screen,date[i],8+i*9+(i>=4?3:0)+(i>=6?3:0),51,6,10,1);
    screen.line(44,56,46,56);
    screen.line(65,56,67,56);
    digit(screen,now.day_of_week==1 ? 7 : now.day_of_week-1,99,51,6,10,1);
    digit(screen,now.second/10,111,51,6,10,1);
    digit(screen,now.second%10,119,51,6,10,1);
  }
  if (ringing_) screen.rectangle(0,0,128,64);
}
}  // namespace esphome::webclock
