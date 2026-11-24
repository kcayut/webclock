#include "alarm_wav.h"

#include <cassert>
#include <string>

namespace {

void append_le(std::string &out, uint32_t number, size_t bytes) {
  for (size_t i = 0; i < bytes; ++i) out.push_back(static_cast<char>((number >> (i * 8)) & 0xff));
}

std::string chunk(const char *tag, const std::string &contents) {
  std::string result(tag);
  append_le(result, contents.size(), 4);
  result += contents;
  if (contents.size() % 2) result.push_back('\0');
  return result;
}

std::string format(uint16_t encoding = 1, uint16_t channels = 1, uint32_t rate = 16000, uint16_t bits = 16) {
  std::string result;
  const uint16_t frame_bytes = channels * bits / 8;
  append_le(result, encoding, 2);
  append_le(result, channels, 2);
  append_le(result, rate, 4);
  append_le(result, rate * frame_bytes, 4);
  append_le(result, frame_bytes, 2);
  append_le(result, bits, 2);
  return chunk("fmt ", result);
}

std::string wave(const std::string &chunks) {
  std::string result = "RIFF";
  append_le(result, 4 + chunks.size(), 4);
  return result + "WAVE" + chunks;
}

void check(const std::string &bytes, uint32_t expected, int first_byte = EOF) {
  FILE *file = std::tmpfile();
  assert(file);
  assert(std::fwrite(bytes.data(), 1, bytes.size(), file) == bytes.size());
  assert(std::fflush(file) == 0);
  assert(rlcd_audio::wav_payload(file) == expected);
  if (expected) assert(std::fgetc(file) == first_byte);
  std::fclose(file);
}

}  // namespace

int main() {
  const std::string pcm = chunk("data", "abcd");
  const std::string good = wave(format() + pcm);
  check(good, 4, 'a');
  check(wave(format() + chunk("LIST", "odd") + pcm), 4, 'a');
  const uint32_t short_bytes = 2 * rlcd_audio::SAMPLE_RATE * sizeof(int16_t);
  check(wave(format() + chunk("data", std::string(short_bytes, 's'))), short_bytes, 's');
  check(wave(format() + chunk("data", std::string(rlcd_audio::MAX_PCM_BYTES, 'x'))),
        rlcd_audio::MAX_PCM_BYTES, 'x');
  const std::string long_wave =
      wave(format() + chunk("data", std::string(180 * rlcd_audio::SAMPLE_RATE * sizeof(int16_t), 'y')));
  check(long_wave, rlcd_audio::MAX_PCM_BYTES, 'y');
  check(long_wave.substr(0, long_wave.size() - 2), 0);
  check(wave(format(3) + pcm), 0);
  check(wave(format(1, 2) + pcm), 0);
  check(wave(format(1, 1, 44100) + pcm), 0);
  check(wave(format(1, 1, 16000, 8) + pcm), 0);
  check(wave(format() + chunk("data", "odd")), 0);
  check(wave(format() + chunk("data", "")), 0);
  check(wave(pcm + format()), 0);
  check(wave(format() + format() + pcm), 0);
  check(good.substr(0, good.size() - 1), 0);
  check("not a WAV", 0);
  std::string invalid_data_size = good;
  invalid_data_size.replace(40, 4, 4, '\xff');
  check(invalid_data_size, 0);
  static_assert(rlcd_audio::FALLBACK.front() == 0 && rlcd_audio::FALLBACK.back() == 0);
  static_assert(rlcd_audio::FALLBACK[160] != 0 && rlcd_audio::FALLBACK[8160] != 0);
}
