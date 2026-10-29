"""تصویرهای نیومورفیسم (برجسته/فرورفته/دکمه‌ی نارنجی) با Pillow؛ مستقل از Kivy و قابل تست. پالت‌ها همان نسخه‌ی ویندوز."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface_hi: str
    surface_lo: str
    light: tuple
    dark: tuple
    text: str
    muted: str
    accent: str
    accent2: str
    teal: str
    violet: str
    pink: str
    ok: str
    err: str
    field: str


LIGHT = Palette("light", bg="#e7ecf2", surface_hi="#eff3f8", surface_lo="#dde4ec",
                light=(255, 255, 255, 235), dark=(163, 177, 198, 190),
                text="#3b475a", muted="#8793a5", accent="#ff9a3c", accent2="#ff5f45",
                teal="#2cc3b4", violet="#8b72f0", pink="#f0679b", ok="#1f9d78", err="#d9534f", field="#dfe6ee")
DARK = Palette("dark", bg="#262a33", surface_hi="#2c313b", surface_lo="#22262e",
               light=(58, 65, 80, 230), dark=(12, 14, 18, 230),
               text="#e7eaf0", muted="#8a93a5", accent="#ff9a3c", accent2="#ff5f45",
               teal="#34d1c1", violet="#9d87ff", pink="#ff7aa9", ok="#3ddc97", err="#ff7b72", field="#20242b")


def hexrgb(c: str) -> tuple:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def rgba01(c: str, a: float = 1.0) -> tuple:
    r, g, b = hexrgb(c)
    return r / 255.0, g / 255.0, b / 255.0, a


def _rr(size, box, radius, fill=255):
    im = Image.new("L", size, 0)
    ImageDraw.Draw(im).rounded_rectangle(box, radius=max(0, radius), fill=fill)
    return im


def _tint(mask: Image.Image, rgba: tuple) -> Image.Image:
    img = Image.new("RGBA", mask.size, tuple(rgba[:3]) + (0,))
    img.putalpha(mask.point(lambda v: v * rgba[3] // 255))
    return img


def _gradient(size, c1, c2) -> Image.Image:
    """گرادیان مورب c1 (بالا-چپ) → c2 (پایین-راست)."""
    w, h = size
    g = Image.linear_gradient("L").resize((w, h))                    # بالا→پایین
    gx = Image.linear_gradient("L").rotate(90).resize((w, h))        # چپ→راست (تقریب)
    t = ImageChops.add(g.point(lambda v: v // 2), gx.point(lambda v: v // 2))
    a = Image.new("RGB", (w, h), tuple(c1))
    b = Image.new("RGB", (w, h), tuple(c2))
    return Image.composite(b, a, t)


def raised(w: int, h: int, radius: int, m: int, off: int, blur: int, pal: Palette, glow=None,
           body=None, pressed: bool = False) -> Image.Image:
    """کارت/دکمه‌ی برجسته؛ اندازه‌ی کل w×h و بدنه با حاشیه‌ی m. body: None=سطح معمولی، یا (rgb1, rgb2) برای دکمه‌ی رنگی."""
    if pressed:
        return inset(w, h, radius, m, off, blur, pal, body=body)
    bw, bh = max(2, w - 2 * m), max(2, h - 2 * m)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dark = glow if glow else pal.dark
    for rgba, d in ((pal.light, -off), (dark, off)):
        box = (m + d, m + d, m + bw - 1 + d, m + bh - 1 + d)
        mask = _rr((w, h), box, radius).filter(ImageFilter.GaussianBlur(max(1, blur / 2)))
        out = Image.alpha_composite(out, _tint(mask, rgba))
    c1, c2 = body if body else (hexrgb(pal.surface_hi), hexrgb(pal.surface_lo))
    grad = _gradient((bw, bh), c1, c2).convert("RGBA")
    grad.putalpha(_rr((bw, bh), (0, 0, bw - 1, bh - 1), radius))
    out.alpha_composite(grad, (m, m))
    return out


def inset(w: int, h: int, radius: int, m: int, off: int, blur: int, pal: Palette, body=None) -> Image.Image:
    bg = body[0] if body else hexrgb(pal.field)
    box = (m, m, w - m - 1, h - m - 1)
    body_mask = _rr((w, h), box, radius)
    out = _tint(body_mask, tuple(bg) + (255,))
    for rgba, d in ((pal.dark, off), (pal.light, -off)):
        shifted = _rr((w, h), (box[0] + d, box[1] + d, box[2] + d, box[3] + d), radius)
        inner = ImageChops.subtract(body_mask, shifted).filter(ImageFilter.GaussianBlur(max(1, blur / 2)))
        inner = ImageChops.multiply(inner, body_mask)
        out = Image.alpha_composite(out, _tint(inner, rgba))
    return out


def make(kind: str, w: int, h: int, pal: Palette, scale: float = 1.0, pressed: bool = False,
         enabled: bool = True) -> Image.Image:
    """kind: card | inset | button | primary | round | tile | seg | seg_on. scale = px به‌ازای هر dp (برای حاشیه/سایه)."""
    s = max(1.0, scale)
    m = int(10 * s)
    off = max(2, int(4 * s))
    blur = max(4, int(10 * s))
    w, h = max(w, 2 * m + 4), max(h, 2 * m + 4)
    if kind == "inset":
        return inset(w, h, int(18 * s), m, off, blur, pal)
    if kind == "card":
        return raised(w, h, int(22 * s), m, off, blur, pal)
    if kind == "tile":
        return raised(w, h, int(24 * s), m, off, blur, pal, pressed=pressed)
    r = (h - 2 * m) // 2
    if kind == "primary":
        a, b = hexrgb(pal.accent), hexrgb(pal.accent2)
        glow = hexrgb(pal.accent2) + ((120 if enabled else 40),)
        if not enabled:
            a, b = hexrgb(pal.field), hexrgb(pal.field)
        return raised(w, h, r, m, off, blur, pal, glow=glow, body=(a, b), pressed=pressed)
    if kind == "seg_on":
        return inset(w, h, r, m, max(2, off // 2), max(3, blur // 2), pal)
    return raised(w, h, r, m, max(2, off // (1 if kind != "seg" else 2)), blur if kind != "seg" else max(3, blur // 2),
                  pal, pressed=pressed)
