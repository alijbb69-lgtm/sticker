"""ساخت یک قالب آزمایشی «Outline شده» شبیه ساختار استیکرهای صرافی.

این فایل جایگزین قالب واقعی نیست؛ فقط برای تست خودکار و تمرین با برنامه است. ساختار آن عمداً
شبیه خروجی Bodymovin از متن‌های Outline شده است: نام لایه‌ها مبهم («Shape Layer N»)، متن‌ها به‌صورت
گروه‌های مسیر، ترنسفورم و انیمیشن روی گروه/لایه، parent، یک خوشه‌ی تک‌حرف‌به‌حرف و عناصر تزئینی.
"""
from __future__ import annotations

from ..calendars.jalali import DayInfo, day_info
from ..vector_text.engine import contours_to_shape_items, layout_text, place_contours
from ..vector_text.fonts import FontFace, default_font_path


def _static(v, ix=0):
    return {"a": 0, "k": v, "ix": ix}


def _ease_kf(t, s, hold=False, out=(0.3, 0.0), inn=(0.7, 1.0)):
    kf = {"t": t, "s": s, "o": {"x": [out[0]], "y": [out[1]]}, "i": {"x": [inn[0]], "y": [inn[1]]}}
    if hold:
        kf["h"] = 1
    return kf


def _tr(p, a=(0, 0), s=None, r=0, o=None):
    return {"ty": "tr", "a": _static(list(a), 1), "p": _static(list(p), 2),
            "s": s if s is not None else _static([100, 100], 3), "r": _static(r, 6),
            "o": o if o is not None else _static(100, 7), "sk": _static(0, 4), "sa": _static(0, 5), "nm": "Transform"}


def _pop_scale(delay: int, op: int = 180):
    return {"a": 1, "ix": 3, "k": [
        _ease_kf(delay, [0, 0, 100]),
        _ease_kf(delay + 20, [100, 100, 100], hold=True),
        _ease_kf(op - 25, [100, 100, 100]),
        {"t": op - 5, "s": [0, 0, 100]},
    ]}


def _fill(rgb):
    return {"ty": "fl", "c": _static(list(rgb) + [1], 4), "o": _static(100, 5), "r": 1, "bm": 0, "nm": "Fill 1"}


def _text_group(contours_abs, center, color, delay, name="Group"):
    """گروه متن: رأس‌ها نسبت به مرکز (anchor=0 ، position=center) تا ماتریس گروه غیرهمانی باشد."""
    rel = [c.transformed(1, 1, -center[0], -center[1]) for c in contours_abs]
    return {"ty": "gr", "nm": name,
            "it": contours_to_shape_items(rel, nd=2) + [_fill(color), _tr(center, s=_pop_scale(delay))]}


def _layer(ind, name, shapes, ks=None, parent=None, op=180):
    d = {"ddd": 0, "ind": ind, "ty": 4, "nm": name, "sr": 1,
         "ks": ks or {"o": _static(100, 11), "r": _static(0, 10), "p": _static([0, 0, 0], 2),
                      "a": _static([0, 0, 0], 1), "s": _static([100, 100, 100], 6)},
         "ao": 0, "shapes": shapes, "ip": 0, "op": op, "st": 0, "bm": 0}
    if parent is not None:
        d["parent"] = parent
    return d


def build_sample_template(font_path: str | None = None, day: DayInfo | None = None,
                          combined_weekday: bool = False) -> dict:
    day = day or day_info(1405, 8, 2)
    face = FontFace(font_path or default_font_path(True))
    f = day.fields()

    def block(text, cx, cy, h, base_dir="auto"):
        lt = layout_text(text, face, face, base_dir=base_dir)
        bb = lt.bbox()
        k = h / (bb[3] - bb[1])
        # مرکز جوهر روی (cx, cy)
        tx = cx - (bb[0] + bb[2]) / 2 * k
        ty = cy + (bb[1] + bb[3]) / 2 * k
        return lt, place_contours(lt.contours(), k, tx, ty), (cx, cy)

    white, gold, cyan, pink = (1, 1, 1), (0.98, 0.78, 0.2), (0.3, 0.85, 0.95), (0.95, 0.4, 0.6)
    layers = []
    # لایه‌های بالا → پایین
    # ۱) سال شمسی: خوشه‌ی تک‌حرف‌به‌حرف
    lt, _abs, _c = block(f["j_year"], 150, 425, 42)
    groups = []
    for gi, g in enumerate([g for g in lt.glyphs if g.contours]):
        cs = place_contours(g.contours, 42 / (lt.bbox()[3] - lt.bbox()[1]), 0, 0)
        # جای واقعی حرف: همان تبدیل کل بلوک
        cs_abs = []
        k = 42 / (lt.bbox()[3] - lt.bbox()[1])
        bb = lt.bbox()
        tx = 150 - (bb[0] + bb[2]) / 2 * k
        ty = 425 + (bb[1] + bb[3]) / 2 * k
        cs_abs = place_contours(g.contours, k, tx, ty)
        xs = [x for c in cs_abs for x, _ in c.v]
        ys = [y for c in cs_abs for _, y in c.v]
        center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        groups.append(_text_group(cs_abs, center, white, 10 + gi * 6, f"Glyph {gi}"))
    layers.append(_layer(1, "Shape Layer 9", list(reversed(groups))))
    # ۲) ماه و سال میلادی
    _, a, c = block(f["g_year"], 370, 425, 42)
    g_year = _text_group(a, c, white, 28, "Group 2")
    _, a, c = block(f["g_month_abbr"], 370, 335, 50)
    g_mon = _text_group(a, c, pink, 22, "Group 1")
    layers.append(_layer(2, "Shape Layer 8", [g_year, g_mon]))
    # ۳) ماه شمسی با parent
    _, a, c = block(f["j_month_name"], 150, 335, 54)
    layers.append(_layer(3, "Shape Layer 7", [_text_group(a, c, cyan, 16, "Group 1")], parent=8))
    # ۴) روز هفته: دو لایه‌ی جدا (پیش‌فرض) یا یک لایه‌ی ترکیبی «شنبه SATURDAY»
    if combined_weekday:
        _, a, c = block(f"{f['wd_fa']} {f['wd_en']}", 256, 75, 34, base_dir="rtl")
        layers.append(_layer(4, "Shape Layer 6", [_text_group(a, c, gold, 4, "Group 1")]))
    else:
        _, a, c = block(f["wd_fa"], 330, 75, 34, base_dir="rtl")
        layers.append(_layer(4, "Shape Layer 6", [_text_group(a, c, gold, 4, "Group 1")]))
        _, a, c = block(f["wd_en"], 170, 78, 22, base_dir="ltr")
        layers.append(_layer(10, "Shape Layer 10", [_text_group(a, c, gold, 6, "Group 1")]))
    # ۵) روزها
    _, a, c = block(f["g_day2"], 372, 225, 90)
    g_d = _text_group(a, c, white, 12, "Group 2")
    _, a, c = block(f["j_day2"], 140, 225, 90)
    j_d = _text_group(a, c, gold, 8, "Group 1")
    ks = {"o": {"a": 1, "ix": 11, "k": [_ease_kf(0, [0]), _ease_kf(12, [100]), {"t": 175, "s": [100]}]},
          "r": _static(0, 10), "p": _static([0, 0, 0], 2), "a": _static([0, 0, 0], 1), "s": _static([100, 100, 100], 6)}
    layers.append(_layer(5, "Shape Layer 5", [g_d, j_d], ks=ks))
    # ۶) عنصر تزئینی: ستاره‌ی مسیری (کاندید گمراه‌کننده) و حلقه با trim و چرخش
    star = _star_path(256, 150, 22, 9, 5)
    deco = {"ty": "gr", "nm": "Star", "it": [{"ty": "sh", "ix": 1, "ks": _static(star, 2), "nm": "Path 1"},
                                              _fill(gold), _tr([0, 0])]}
    layers.append(_layer(6, "Shape Layer 3", [deco]))
    ring = {"ty": "gr", "nm": "Ring", "it": [
        {"ty": "el", "d": 1, "s": _static([440, 440], 2), "p": _static([0, 0], 3), "nm": "Ellipse Path 1"},
        {"ty": "st", "c": _static([0.5, 0.8, 1, 1], 3), "o": _static(100, 4), "w": _static(4, 5), "lc": 2, "lj": 2, "nm": "Stroke 1"},
        {"ty": "tm", "s": _static(0, 1), "e": _static(100, 2), "o": _static(0, 3), "m": 1, "nm": "Trim Paths 1"},
        _tr([0, 0])]}
    ring_ks = {"o": _static(100, 11), "p": _static([256, 256, 0], 2), "a": _static([0, 0, 0], 1),
               "s": _static([100, 100, 100], 6),
               "r": {"a": 1, "ix": 10, "k": [_ease_kf(0, [0], out=(0, 0), inn=(1, 1)), {"t": 180, "s": [360]}]}}
    layers.append(_layer(7, "Shape Layer 2", [ring], ks=ring_ks))
    # ۷) null (والد ماه شمسی) با انیمیشن موقعیت
    null = {"ddd": 0, "ind": 8, "ty": 3, "nm": "Null 1", "sr": 1,
            "ks": {"o": _static(0, 11), "r": _static(0, 10), "a": _static([0, 0, 0], 1), "s": _static([100, 100, 100], 6),
                   "p": {"a": 1, "ix": 2, "k": [_ease_kf(0, [0, 0, 0]), _ease_kf(90, [0, -6, 0]), {"t": 180, "s": [0, 0, 0]}]}},
            "ao": 0, "ip": 0, "op": 180, "st": 0, "bm": 0}
    layers.append(null)
    # ۸) پس‌زمینه
    bg = {"ty": "gr", "nm": "BG", "it": [
        {"ty": "rc", "d": 1, "s": _static([512, 512], 2), "p": _static([256, 256], 3), "r": _static(40, 4), "nm": "Rect"},
        _fill((0.07, 0.1, 0.22)), _tr([0, 0])]}
    layers.append(_layer(9, "Shape Layer 1", [bg]))
    return {"v": "5.5.2", "fr": 60, "ip": 0, "op": 180, "w": 512, "h": 512, "nm": "sample_exchange_date",
            "ddd": 0, "assets": [], "layers": layers, "markers": []}


def _star_path(cx, cy, r1, r2, n):
    import math
    v = []
    for k in range(n * 2):
        r = r1 if k % 2 == 0 else r2
        a = -math.pi / 2 + k * math.pi / n
        v.append([cx + r * math.cos(a), cy + r * math.sin(a)])
    z = [[0, 0]] * len(v)
    return {"i": z, "o": z, "v": v, "c": True}
