#pragma once
#include <cstdint>
#include <string>

namespace deskclock {
inline uint32_t next_char(const std::string &s, size_t &i) {
  uint8_t lead = s[i++];
  if (lead < 0x80) return lead;
  int count = lead < 0xc2 ? 0 : lead < 0xe0 ? 1 : lead < 0xf0 ? 2 : lead <= 0xf4 ? 3 : 0;
  if (!count || i + count > s.size()) return '?';
  uint32_t code = lead & (0x7f >> (count + 1));
  while (count--) {
    uint8_t c = s[i];
    if ((c & 0xc0) != 0x80) return '?';
    ++i;
    code = (code << 6) | (c & 0x3f);
  }
  return code;
}
inline int tile_index(uint32_t cp) {
  constexpr unsigned ranges[][2] = {{0x20,0x7e},{0x2000,0x206f},{0x3000,0x30ff},
                                     {0x4e00,0x9fff},{0xff00,0xffef},{0xd7,0xd7},{0x25cf,0x25cf}};
  int base = 0;
  for (auto &r : ranges) {
    if (cp >= r[0] && cp <= r[1]) return base + cp - r[0];
    base += r[1] - r[0] + 1;
  }
  return '?' - 0x20;
}
struct Ticker {
  static constexpr int columns = 27;
  size_t start{0};
  uint32_t last{0};
  void reset(uint32_t now) { start = 0; last = now; }
  bool advance(const std::string &s, uint32_t now) {
    if (s.empty() || now - last < 8000) return false;
    last = now;
    size_t end = start, step = start;
    for (int n = 0; n < columns && end < s.size(); ++n) {
      next_char(s, end);
      if (n == 7) step = end;
    }
    const size_t prev = start;
    start = end < s.size() ? step : 0;
    return prev != start;
  }
};
inline Ticker ticker;
inline int line_width(const std::string &s) {
  size_t i = 0;
  int n = 0;
  while (i < s.size()) { next_char(s, i); ++n; }
  return n * 28;
}
template<class Display, class Atlas, class Ink>
void draw_line(Display &screen, const Atlas &atlas, const std::string &text,
               size_t pos, int y, Ink ink, int x = 22, int scale = 2) {
  for (int n = 0; pos < text.size() && n < Ticker::columns; ++n) {
    int tile = tile_index(next_char(text, pos));
    for (int row = 0; row < 16; ++row) {
      for (int col = 0; col < 14; ++col) {
        if (atlas.get_pixel(tile % 128 * 14 + col, tile / 128 * 16 + row).is_on())
          screen.filled_rectangle(x + (14*n + col)*scale, y + row*scale, scale, scale, ink);
      }
    }
  }
}
}  // namespace deskclock
