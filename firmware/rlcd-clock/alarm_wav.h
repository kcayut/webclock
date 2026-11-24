#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <sys/stat.h>

namespace rlcd_audio {

inline constexpr uint32_t SAMPLE_RATE = 16000;
inline constexpr uint32_t MAX_PCM_BYTES = 60 * SAMPLE_RATE * sizeof(int16_t);

inline uint16_t read_le16(const uint8_t *p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }

inline uint32_t read_le32(const uint8_t *p) { return read_le16(p) | (uint32_t(read_le16(p + 2)) << 16); }

// Validates the full declared data range, then returns the prefix to read.
inline uint32_t wav_payload(FILE *file) {
  struct stat info{};
  if (fstat(fileno(file), &info) != 0 || info.st_size < 44 || std::fseek(file, 0, SEEK_SET) != 0) return 0;

  uint8_t header[12];
  if (std::fread(header, 1, sizeof(header), file) != sizeof(header) ||
      std::memcmp(header, "RIFF", 4) || std::memcmp(header + 8, "WAVE", 4)) return 0;
  const uint32_t riff_size = read_le32(header + 4);
  if (riff_size < 36 || riff_size > static_cast<uint64_t>(info.st_size - 8)) return 0;

  uint32_t remaining = riff_size - 4;
  bool pcm = false;
  // shortcut: scan at most 64 chunks, increase only if real exported clips exceed this.
  for (int i = 0; i < 64 && remaining >= 8; ++i) {
    uint8_t chunk[8];
    if (std::fread(chunk, 1, sizeof(chunk), file) != sizeof(chunk)) return 0;
    const uint32_t size = read_le32(chunk + 4);
    remaining -= sizeof(chunk);
    if (size > remaining || (size == remaining && (size & 1))) return 0;
    const uint32_t padded = size + (size & 1);
    uint32_t unread = padded;
    if (std::memcmp(chunk, "fmt ", 4) == 0) {
      uint8_t fmt[16];
      if (pcm || size < sizeof(fmt) || std::fread(fmt, 1, sizeof(fmt), file) != sizeof(fmt)) return 0;
      pcm = read_le16(fmt) == 1 && read_le16(fmt + 2) == 1 && read_le32(fmt + 4) == SAMPLE_RATE &&
            read_le32(fmt + 8) == SAMPLE_RATE * 2 && read_le16(fmt + 12) == 2 && read_le16(fmt + 14) == 16;
      if (!pcm) return 0;
      unread -= sizeof(fmt);
    } else if (std::memcmp(chunk, "data", 4) == 0) {
      return pcm && size % sizeof(int16_t) == 0 ? std::min(size, MAX_PCM_BYTES) : 0;
    }
    if (std::fseek(file, unread, SEEK_CUR) != 0) return 0;
    remaining -= padded;
  }
  return 0;
}

constexpr std::array<int16_t, SAMPLE_RATE> make_fallback() {
  std::array<int16_t, SAMPLE_RATE> samples{};
  for (size_t i = 0; i < samples.size(); ++i) {
    const int beat_sample = i % (SAMPLE_RATE / 2);
    if (beat_sample >= 3200) continue;
    const int period = i < SAMPLE_RATE / 2 ? 20 : 16;
    const int phase = beat_sample % period;
    const int triangle = phase < period / 2 ? phase : period - phase;
    const int fade = beat_sample < 160 ? beat_sample : (beat_sample > 3040 ? 3200 - beat_sample : 160);
    samples[i] = (triangle * 4 - period) * 1200 * fade / 160;
  }
  return samples;
}

inline constexpr auto FALLBACK = make_fallback();

}  // namespace rlcd_audio
