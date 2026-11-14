"""Generate the ShieldVPN launcher icons (shield mark) for every mipmap density.

Run from the ShieldVPN project root:
    python scripts/generate_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

RES = Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "res"

DENSITIES = {
    "mdpi": 1.0,
    "hdpi": 1.5,
    "xhdpi": 2.0,
    "xxhdpi": 3.0,
    "xxxhdpi": 4.0,
}

BG_TOP = (11, 18, 32)
BG_BOTTOM = (23, 38, 66)
GREEN_TOP = (34, 197, 94)
GREEN_BOTTOM = (21, 128, 61)
CHECK = (255, 255, 255)

SS = 4  # supersampling factor


def bezier(p0, p1, p2, p3, steps=48):
    out = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        out.append((x, y))
    return out


def shield_points(size, inset=0.0):
    """Shield silhouette inside a size x size box scaled by (1 - 2*inset) and centered."""
    scale = 1.0 - 2 * inset
    off = inset * size

    def pt(x, y):
        return (off + x * scale * size, off + y * scale * size)

    raw = [(0.5, 0.05), (0.92, 0.22), (0.92, 0.5)]
    raw += bezier((0.92, 0.5), (0.92, 0.76), (0.73, 0.9), (0.5, 0.97))[1:]
    raw += bezier((0.5, 0.97), (0.27, 0.9), (0.08, 0.76), (0.08, 0.5))[1:]
    raw += [(0.08, 0.22)]
    return [pt(x, y) for x, y in raw]


def vertical_gradient(size, top, bottom):
    grad = Image.new("RGB", (1, size), top)
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel(
            (0, y),
            (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            ),
        )
    return grad.resize((size, size))


def rounded_mask(size, radius_ratio=0.22):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=255
    )
    return mask


def circle_mask(size):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def draw_shield(img, size, inset, gradient):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(shield_points(size, inset), fill=255)
    layer.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(layer)
    w = size * (1 - 2 * inset)
    ox = size * inset
    oy = size * inset
    stroke = max(1, int(w * 0.095))
    draw.line(
        [
            (ox + w * 0.32, oy + w * 0.50),
            (ox + w * 0.45, oy + w * 0.64),
            (ox + w * 0.70, oy + w * 0.37),
        ],
        fill=CHECK,
        width=stroke,
        joint="curve",
    )
    # round line caps
    r = stroke / 2
    for cx, cy in ((0.32, 0.50), (0.70, 0.37)):
        draw.ellipse(
            (ox + w * cx - r, oy + w * cy - r, ox + w * cx + r, oy + w * cy + r),
            fill=CHECK,
        )
    img.alpha_composite(layer)


def make_launcher(size, round_icon=False):
    big = size * SS
    bg = vertical_gradient(big, BG_TOP, BG_BOTTOM).convert("RGBA")
    mask = circle_mask(big) if round_icon else rounded_mask(big)
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), mask)

    gradient = vertical_gradient(big, GREEN_TOP, GREEN_BOTTOM).convert("RGBA")
    draw_shield(icon, big, 0.21 if round_icon else 0.19, gradient)
    return icon.resize((size, size), Image.LANCZOS)


def make_foreground(size):
    big = size * SS
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    gradient = vertical_gradient(big, GREEN_TOP, GREEN_BOTTOM).convert("RGBA")
    # Adaptive icons: keep the mark inside the 66/108 safe zone.
    draw_shield(icon, big, 0.235, gradient)
    return icon.convert("RGBA").resize((size, size), Image.LANCZOS)


def main():
    for density, factor in DENSITIES.items():
        folder = RES / f"mipmap-{density}"
        folder.mkdir(parents=True, exist_ok=True)

        launcher = int(48 * factor)
        make_launcher(launcher).save(folder / "ic_launcher.png")
        make_launcher(launcher, round_icon=True).save(folder / "ic_launcher_round.png")
        make_foreground(int(108 * factor)).save(folder / "ic_launcher_foreground.png")
        make_foreground(int(320 * factor)).save(folder / "ic_banner_foreground.png")
        print(f"wrote {folder}")


if __name__ == "__main__":
    main()
