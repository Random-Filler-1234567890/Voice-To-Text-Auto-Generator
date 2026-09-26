"""Generates VoiceFlow's app icon as a 1024x1024 PNG.

Runs anywhere Pillow is installed (including this Linux dev environment) -
it's pure image drawing, no macOS APIs involved. ``build_macos_app.sh``
then converts the PNG into a proper multi-resolution .icns using macOS's
built-in ``iconutil``/``sips``, which only exist on macOS.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

SIZE = 1024
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icon_1024.png")

# A calm indigo-to-violet gradient background with a simple rounded-square
# "app icon" silhouette, plus a stylized microphone/waveform glyph - avoids
# needing any external image assets or fonts.
COLOR_TOP = (99, 102, 241)  # indigo-500
COLOR_BOTTOM = (139, 92, 246)  # violet-500
GLYPH_COLOR = (255, 255, 255, 235)


def _rounded_rect_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
    return mask


def _gradient_background(size: int) -> Image.Image:
    top = Image.new("RGB", (size, size), COLOR_TOP)
    bottom = Image.new("RGB", (size, size), COLOR_BOTTOM)
    mask = Image.new("L", (size, size))
    mask_data = []
    for y in range(size):
        value = int(255 * (y / (size - 1)))
        mask_data.extend([value] * size)
    mask.putdata(mask_data)
    return Image.composite(bottom, top, mask)


def _draw_microphone(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    body_w = int(180 * scale)
    body_h = int(300 * scale)
    body_top = cy - int(170 * scale)

    draw.rounded_rectangle(
        [cx - body_w // 2, body_top, cx + body_w // 2, body_top + body_h],
        radius=body_w // 2,
        fill=GLYPH_COLOR,
    )

    arc_r = int(170 * scale)
    arc_bbox = [cx - arc_r, body_top - int(20 * scale), cx + arc_r, body_top + body_h + int(60 * scale)]
    draw.arc(arc_bbox, start=25, end=155, fill=GLYPH_COLOR, width=int(26 * scale))

    stand_top = body_top + body_h + int(60 * scale)
    stand_bottom = stand_top + int(90 * scale)
    draw.line([(cx, stand_top), (cx, stand_bottom)], fill=GLYPH_COLOR, width=int(26 * scale))

    base_w = int(160 * scale)
    draw.line(
        [(cx - base_w // 2, stand_bottom), (cx + base_w // 2, stand_bottom)],
        fill=GLYPH_COLOR,
        width=int(26 * scale),
    )


def _draw_waveform_arcs(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    for i, r in enumerate((260, 330, 400)):
        radius = int(r * scale)
        width = max(2, int((18 - i * 4) * scale))
        alpha_glyph = (255, 255, 255, max(40, 140 - i * 45))
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        draw.arc(bbox, start=200, end=340, fill=alpha_glyph, width=width)


def main() -> None:
    scale = SIZE / 1024
    bg = _gradient_background(SIZE).convert("RGBA")

    glyph_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glyph_draw = ImageDraw.Draw(glyph_layer)
    cx, cy = SIZE // 2, int(SIZE * 0.52)
    _draw_waveform_arcs(glyph_draw, cx, cy, scale)
    _draw_microphone(glyph_draw, cx, cy, scale)

    composed = Image.alpha_composite(bg, glyph_layer)

    mask = _rounded_rect_mask(SIZE, radius=int(SIZE * 0.22))
    final = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    final.paste(composed, (0, 0), mask)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    final.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
