#pragma once

#include "alarm_core.h"
#include "esphome/core/component.h"
#include "esphome/components/time/real_time_clock.h"
#include "esphome/components/output/float_output.h"
#include "esphome/components/display/display.h"
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <memory>
#include <string>

namespace esphome::webclock {

class WebClock : public Component {
 public:
  void set_clock(time::RealTimeClock *clock) { clock_ = clock; }
  void set_buzzer(output::FloatOutput *buzzer) { buzzer_ = buzzer; }
  void set_server_url(const std::string &value) { server_url_ = value; }
  void set_api_token(const std::string &value) { api_token_ = value; }
  void set_device_name(const std::string &value) { device_name_ = value; }
  void set_volume_limit(float value) { volume_limit_ = value; }
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }
  void draw(display::Display &screen);
  void stop();

 protected:
  // Network/JSON work stays on a worker; only the ESPHome loop touches output/display.
  struct Update { Snapshot *snapshot; bool authorized; };
  static void task_entry_(void *arg);
  void sync_task_();
  void publish_(const Snapshot *snapshot, bool authorized);
  bool record_fire_(int64_t stamp);
  time::RealTimeClock *clock_{nullptr};
  output::FloatOutput *buzzer_{nullptr};
  std::string server_url_, api_token_, device_name_, device_id_, scope_;
  QueueHandle_t updates_{nullptr}, applied_{nullptr};
  std::unique_ptr<Snapshot> snapshot_;
  bool authorized_{false}, ringing_{false}, storage_ready_{false};
  float volume_limit_{0.25f}, ring_level_{0};
  float output_level_{-1};
  uint32_t ring_started_{0};
  int64_t last_fired_{0};
};
}  // namespace esphome::webclock
