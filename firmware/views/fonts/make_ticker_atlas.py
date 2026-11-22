"""Make the 14x16 monochrome Noto Sans TC atlas from the upstream OFL TTF."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Keep in sync with ticker.h. Direct Unicode indexing avoids per-glyph metadata.
ranges = [(0x20, 0x7E), (0x2000, 0x206F), (0x3000, 0x30FF),
          (0x4E00, 0x9FFF), (0xFF00, 0xFFEF), (0xD7, 0xD7), (0x25CF, 0x25CF)]
codes = [i for first, last in ranges for i in range(first, last + 1)]
atlas = Image.new('1', (128 * 14, ((len(codes) + 127) // 128) * 16))
font = ImageFont.truetype(sys.argv[1], 14)
# Threshold grayscale once; retain stroke coverage at this small size.
tile = Image.new('L', (14, 16))
pen = ImageDraw.Draw(tile)
for i, code in enumerate(codes):
    tile.paste(0, (0, 0, 14, 16))
    pen.text((0, 13), chr(code), font=font, anchor='ls', fill=255)
    atlas.paste(tile.point(lambda x: 255 if x >= 82 else 0, '1'), (i % 128 * 14, i // 128 * 16))
atlas.save(Path(__file__).with_name('ticker.png'), optimize=True)
