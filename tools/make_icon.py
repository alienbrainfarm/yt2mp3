from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icon.ico"
SIZE = 256
SCALE = 4


def draw_icon() -> Image.Image:
    canvas = SIZE * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = int(canvas * 0.23)
    draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=radius, fill=(216, 255, 106, 255))

    ink = (17, 21, 7, 255)
    note_x = canvas * 0.38
    note_top = canvas * 0.23
    note_bottom = canvas * 0.66
    stem_width = max(2, int(canvas * 0.055))
    head_radius = canvas * 0.115

    draw.line((note_x, note_bottom, note_x, note_top), fill=ink, width=stem_width)
    draw.line((note_x, note_top, canvas * 0.68, canvas * 0.18), fill=ink, width=stem_width)
    draw.line((canvas * 0.68, canvas * 0.18, canvas * 0.68, canvas * 0.55), fill=ink, width=stem_width)
    draw.ellipse(
        (
            note_x - head_radius,
            note_bottom - head_radius * 0.7,
            note_x + head_radius,
            note_bottom + head_radius * 1.3,
        ),
        fill=ink,
    )
    draw.ellipse(
        (
            canvas * 0.68 - head_radius,
            canvas * 0.55 - head_radius * 0.7,
            canvas * 0.68 + head_radius,
            canvas * 0.55 + head_radius * 1.3,
        ),
        fill=ink,
    )

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.save(OUT, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
