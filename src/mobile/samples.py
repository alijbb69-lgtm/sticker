"""نمونه‌ی متن با یک فونت (برای فهرست فونت‌ها) و بررسی پوشش حروف؛ با موتور برداریِ خودِ برنامه رسم می‌شود (شکل‌دهی درست فارسی)."""
from __future__ import annotations

from PIL import Image, ImageDraw

from ..tgs.replacer import SlotSpec, _box, _em_polys, render_text

SAMPLE_FA = "سلام، نمونه زیرنویس ۱۲۳"
SAMPLE_EN = "Hello, sample caption 123"
FA_PROBE = "آبانشنبهیکجمعهاسفند۰۱۲۳۴۵۶۷۸۹"
EN_PROBE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_CACHE: dict = {}


def sample_image(font_path: str, text: str, color: tuple, height: int = 34, max_width: int = 560) -> Image.Image:
    """متن با فونت داده‌شده، رنگ color، ارتفاع خط ≈ height پیکسل؛ شفاف. اگر فونت خراب باشد تصویر خالی برمی‌گرداند."""
    key = (font_path, text, tuple(color), height, max_width)
    im = _CACHE.get(key)
    if im is not None:
        return im
    try:
        slot = SlotSpec("نمونه", "{x}", fa_font=font_path, en_font=font_path)
        lt = render_text(slot, text)
        polys = _em_polys(lt)
        box = _box(polys)
        if not box:
            raise ValueError("بدون گلیف")
        # مقیاس: ارتفاع «em» ≈ height×0.8
        k = height * 0.8
        w_px = (box[2] - box[0]) * k
        if w_px > max_width:
            k *= max_width / w_px
        S = 3
        W, H = int((box[2] - box[0]) * k) + 6, int(height * 1.5)
        acc = Image.new("L", (W * S, H * S), 0)
        import numpy as np
        a = np.zeros((H * S, W * S), dtype=bool)
        for poly in polys:
            if len(poly) < 3:
                continue
            m = Image.new("1", (W * S, H * S), 0)
            ImageDraw.Draw(m).polygon([((x - box[0]) * k * S + 3 * S, y * k * S + height * S) for x, y in poly], fill=1)
            a ^= np.asarray(m, dtype=bool)
        cov = Image.fromarray((a * 255).astype("uint8"), "L").resize((W, H), Image.LANCZOS)
        im = Image.new("RGBA", (W, H), tuple(color) + (0,))
        im.putalpha(cov)
    except Exception:  # noqa: BLE001
        im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    _CACHE[key] = im
    return im


def missing_chars(font_path: str, probe: str) -> list[str]:
    try:
        from ..vector_text.fonts import FontFace
        face = FontFace(font_path)
        return [c for c in dict.fromkeys(probe) if not face.has_char(c)
                and not any(face.has_char(x) for x in _alt(c))]
    except Exception:  # noqa: BLE001
        return list(probe)


def _alt(c: str):
    return []
