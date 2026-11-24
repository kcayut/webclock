#pragma once

#include "alarm_wav.h"
#include "esphome/components/speaker/speaker.h"
#include "esphome/components/switch/switch.h"
#include "esphome/core/log.h"

#include <atomic>
#include <cstdlib>
#include <driver/sdmmc_host.h>
#include <esp_heap_caps.h>
#include <esp_pm.h>
#include <esp_vfs_fat.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <sdmmc_cmd.h>

namespace rlcd_audio {

class AlarmAudio {
 public:
  bool update(float level, uint32_t now, esphome::speaker::Speaker &speaker, esphome::switch_::Switch &amp) {
    if (level <= 0.0f) {
      if (active_) {
        if (loading_) cancel_read_.store(true);
        amp.turn_off();
        speaker.stop();
        wait_for_stop_ = true;
        std::free(clip_.samples);
        clip_ = {};
        pcm_ = nullptr;
        active_ = false;
        if (locked_) {
          esp_pm_lock_release(lock_);
          locked_ = false;
        }
      }
    } else if (!active_) {
      active_ = true;
      started_ = now;
      offset_ = 0;
      if (!lock_) esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, TAG, &lock_);
      locked_ = lock_ && esp_pm_lock_acquire(lock_) == ESP_OK;
      speaker.set_audio_stream_info(esphome::audio::AudioStreamInfo(16, 1, SAMPLE_RATE));
      speaker.set_volume(0.75f);  // ES8311 unity gain; volume is applied once to PCM below.
      if (!loading_) {
        if (!results_) results_ = xQueueCreate(1, sizeof(Clip));
        cancel_read_.store(false);
        if (results_) loading_ = xTaskCreate(load_card, TAG, 4096, this, 1, nullptr) == pdPASS;
      } else {
        // A prior ring still owns the SD driver. Its result belongs to that ring.
        use_fallback();
      }
    }

    if (loading_) {
      Clip result{};
      const bool in_time = now - started_ < LOAD_TIMEOUT_MS;
      if (xQueueReceive(results_, &result, 0) == pdTRUE) {
        loading_ = false;
        if (active_ && !pcm_ && in_time && result.samples) {
          clip_ = result;
          pcm_ = clip_.samples;
          sample_count_ = clip_.count;
          ESP_LOGI(TAG, "Playing microSD alarm.wav");
        } else {
          std::free(result.samples);
        }
      }
      if (active_ && !pcm_ && !in_time) {
        cancel_read_.store(true);
        use_fallback();
      }
    }
    if (active_ && !pcm_ && !loading_) use_fallback();
    if (wait_for_stop_ && speaker.is_stopped()) wait_for_stop_ = false;
    if (active_ && pcm_ && !wait_for_stop_) {
      int16_t frame[512];
      const float gain = std::min(level, 0.25f);
      size_t next = offset_;
      for (auto &sample : frame) {
        sample = static_cast<int16_t>(pcm_[next++] * gain);
        if (next == sample_count_) next = 0;
      }
      const size_t written = speaker.play(reinterpret_cast<const uint8_t *>(frame), sizeof(frame), 0);
      offset_ = (offset_ + written / sizeof(int16_t)) % sample_count_;
      if (written && !amp.state) amp.turn_on();
    }
    return active_ || loading_;
  }

 private:
  struct Clip {
    int16_t *samples{nullptr};
    uint32_t count{0};
  };

  static constexpr const char *TAG = "rlcd_alarm";
  static constexpr uint32_t LOAD_TIMEOUT_MS = 3000;
  static constexpr const char *MOUNT_POINT = "/rlcd_sd";

  bool read_pcm(FILE *file, int16_t *samples, uint32_t bytes) const {
    auto *data = reinterpret_cast<uint8_t *>(samples);
    for (uint32_t offset = 0; offset < bytes;) {
      const uint32_t size = std::min<uint32_t>(bytes - offset, 16 * 1024);
      if (cancel_read_.load() || std::fread(data + offset, 1, size, file) != size) return false;
      offset += size;
    }
    return true;
  }

  Clip read_card() const {
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
    slot.width = 1;
    slot.clk = GPIO_NUM_38;
    slot.cmd = GPIO_NUM_21;
    slot.d0 = GPIO_NUM_39;
    esp_vfs_fat_sdmmc_mount_config_t mount{};
    mount.max_files = 1;
    sdmmc_card_t *card = nullptr;
    const esp_err_t err = esp_vfs_fat_sdmmc_mount(MOUNT_POINT, &host, &slot, &mount, &card);
    if (err != ESP_OK) {
      ESP_LOGW(TAG, "microSD mount failed: %s", esp_err_to_name(err));
      return {};
    }

    Clip clip{};
    if (FILE *file = std::fopen("/rlcd_sd/alarm.wav", "rb")) {
      const uint32_t bytes = cancel_read_.load() ? 0 : wav_payload(file);
      if (bytes) {
        auto *samples = static_cast<int16_t *>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (samples && read_pcm(file, samples, bytes))
          clip = {samples, bytes / static_cast<uint32_t>(sizeof(int16_t))};
        else
          std::free(samples);
      }
      std::fclose(file);
    }
    esp_vfs_fat_sdcard_unmount(MOUNT_POINT, card);
    return clip;
  }

  static void load_card(void *arg) {
    const auto &audio = *static_cast<AlarmAudio *>(arg);
    const Clip result = audio.read_card();
    if (xQueueSend(audio.results_, &result, 0) != pdTRUE) std::free(result.samples);
    vTaskDelete(nullptr);
  }

  void use_fallback() {
    pcm_ = FALLBACK.data();
    sample_count_ = FALLBACK.size();
    ESP_LOGW(TAG, "microSD alarm.wav unavailable; playing built-in chime");
  }

  QueueHandle_t results_{nullptr};
  esp_pm_lock_handle_t lock_{nullptr};
  Clip clip_{};
  const int16_t *pcm_{nullptr};
  size_t sample_count_{0};
  size_t offset_{0};
  uint32_t started_{0};
  bool active_{false};
  bool loading_{false};
  bool locked_{false};
  bool wait_for_stop_{false};
  std::atomic<bool> cancel_read_{false};
};

inline AlarmAudio alarm;

}  // namespace rlcd_audio
