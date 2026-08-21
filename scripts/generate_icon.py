"""Generate the small TellMeSensei Windows application icon."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SIZES = (16, 24, 32, 48, 64, 128, 256)
BACKGROUND = "#2f4057"
ACCENT = "#1685d8"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default()


def create_icon(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    largest = max(SIZES)
    image = Image.new("RGBA", (largest, largest), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = largest // 32
    draw.rounded_rectangle(
        (margin, margin, largest - margin - 1, largest - margin - 1),
        radius=largest // 6,
        fill=BACKGROUND,
        outline=ACCENT,
        width=max(2, largest // 64),
    )
    ring = (largest * 0.18, largest * 0.18, largest * 0.82, largest * 0.82)
    draw.ellipse(ring, outline="#8fd4ff", width=max(2, largest // 48))
    font = _font(int(largest * 0.48))
    text = "学"
    box = draw.textbbox((0, 0), text, font=font)
    text_x = (largest - (box[2] - box[0])) / 2 - box[0]
    text_y = (largest - (box[3] - box[1])) / 2 - box[1] - largest * 0.02
    draw.text((text_x, text_y), text, font=font, fill="#ffffff")
    image.save(output, format="ICO", sizes=[(size, size) for size in SIZES])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    create_icon(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
