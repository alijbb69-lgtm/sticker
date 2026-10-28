"""شکل‌دهی متن: bidi ساده، اتصال حروف عربی/فارسی، لیگاتور لام‌الف، کرنینگ.

دو پشتیبان وجود دارد:
  * HarfBuzz (uharfbuzz) در صورت نصب بودن — دقیق‌ترین گزینه، با GPOS/GSUB کامل.
  * شکل‌دهنده‌ی داخلی مبتنی بر fontTools — بدون وابستگی اضافه؛ از فرم‌های
    نمایشی یونیکد (cmap) و در صورت نبودن آن‌ها از GSUB (init/medi/fina/isol، rlig/liga) استفاده می‌کند.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .fonts import FontFace

try:  # pragma: no cover - در محیط ساخت نصب نبود
    import uharfbuzz as hb
except Exception:  # noqa: BLE001
    hb = None

ZWNJ = "‌"
ZWJ = "‍"
TATWEEL = "ـ"
_HARAKAT = set(range(0x064B, 0x0660)) | {0x0670} | set(range(0x06D6, 0x06DD)) | set(range(0x06DF, 0x06E9))

_ALEF_LIG = {  # الف بعد از لام: (فرم جدا، فرم پایانی)
    "ا": ("ﻻ", "ﻼ"), "آ": ("ﻵ", "ﻶ"),
    "أ": ("ﻷ", "ﻸ"), "إ": ("ﻹ", "ﻺ"),
}


def _build_forms():
    forms: dict[str, dict[str, str]] = {}
    for cp in list(range(0xFB50, 0xFE00)) + list(range(0xFE70, 0xFF00)):
        dec = unicodedata.decomposition(chr(cp))
        if not dec.startswith("<") or len(dec.split()) != 2:
            continue
        tag, base = dec.split()
        tag = tag.strip("<>")
        if tag in ("initial", "medial", "final", "isolated"):
            base_ch = chr(int(base, 16))
            forms.setdefault(base_ch, {})[tag] = chr(cp)
    return forms


_FORMS = _build_forms()


def joining_type(ch: str) -> str:
    """'D' دو‌طرفه، 'R' راست‌چسب، 'T' شفاف (اعراب)، 'U' بدون اتصال."""
    cp = ord(ch)
    if ch == ZWNJ:
        return "U"
    if ch == ZWJ or ch == TATWEEL:
        return "D"
    if cp in _HARAKAT:
        return "T"
    f = _FORMS.get(ch)
    if f:
        if "initial" in f:
            return "D"
        if "final" in f:
            return "R"
    return "U"


def is_rtl_char(ch: str) -> bool:
    return unicodedata.bidirectional(ch) in ("R", "AL")


def _char_class(ch: str) -> str:
    b = unicodedata.bidirectional(ch)
    if b in ("R", "AL"):
        return "R"
    if b == "L":
        return "L"
    if b in ("EN", "AN"):
        return "N"
    return "X"  # خنثی


@dataclass
class Run:
    text: str
    rtl: bool          # آیا ذاتاً راست‌به‌چپ است (حروف عربی/فارسی)
    kind: str          # 'R' | 'L' | 'N' (عدد) | 'X' (خنثی/فاصله)


def split_runs(text: str, base_dir: str = "auto") -> tuple[list[Run], bool]:
    """متن را به دنباله‌های هم‌جهت می‌شکند و ترتیب «دیداری» را برمی‌گرداند.

    خروجی: (runهای مرتب‌شده از چپ به راست روی صفحه، base_rtl)
    """
    classes = [_char_class(c) for c in text]
    if base_dir == "rtl":
        base_rtl = True
    elif base_dir == "ltr":
        base_rtl = False
    else:
        first = next((k for k in classes if k in ("R", "L")), "L")
        base_rtl = first == "R"
    # حل خنثی‌ها: بین دو جهت یکسان همان جهت؛ وگرنه جهت پایه
    resolved = list(classes)
    last_strong = "R" if base_rtl else "L"
    prev_dir = []
    for k in classes:
        if k in ("R", "L"):
            last_strong = k
        prev_dir.append(last_strong)
    next_dir = [None] * len(text)
    nxt = "R" if base_rtl else "L"
    for idx in range(len(text) - 1, -1, -1):
        if classes[idx] in ("R", "L"):
            nxt = classes[idx]
        next_dir[idx] = nxt
    for idx, k in enumerate(classes):
        if k == "X":
            p, n = prev_dir[idx], next_dir[idx]
            resolved[idx] = p if p == n else ("R" if base_rtl else "L")
        elif k == "N":
            resolved[idx] = "N"
    # گروه‌بندی
    runs: list[Run] = []
    for ch, k in zip(text, resolved):
        if runs and runs[-1].kind == k:
            runs[-1].text += ch
        else:
            runs.append(Run(ch, k == "R", k))
    # عددها: در زمینه‌ی راست‌به‌چپ عددها ترتیب چپ‌به‌راست خود را حفظ می‌کنند
    ordered = list(reversed(runs)) if base_rtl else runs
    return ordered, base_rtl


@dataclass
class ShapedGlyph:
    face: FontFace
    glyph: str
    advance: float      # em
    dx: float = 0.0
    dy: float = 0.0
    char: str = ""      # نویسه‌ی مبدأ (برای گزارش)


def _resolve_forms(text: str) -> list[tuple[str, str]]:
    """برای هر نویسه‌ی دنباله‌ی عربی، (نویسه‌ی فرم نمایشی یا خود نویسه، فرم) را برمی‌گرداند (ترتیب منطقی)."""
    chars = list(text)
    n = len(chars)
    out: list[tuple[str, str]] = []
    k = 0

    def prev_joins(idx: int) -> bool:
        j = idx - 1
        while j >= 0 and joining_type(chars[j]) == "T":
            j -= 1
        return j >= 0 and joining_type(chars[j]) == "D" and out_joined_next[j]

    def next_joinable(idx: int) -> bool:
        j = idx + 1
        while j < n and joining_type(chars[j]) == "T":
            j += 1
        return j < n and joining_type(chars[j]) in ("D", "R")

    out_joined_next = [False] * n
    for idx, ch in enumerate(chars):
        jt = joining_type(ch)
        out_joined_next[idx] = jt == "D" and next_joinable(idx)
    # لام + الف
    results: list[tuple[str, str] | None] = [None] * n
    skip = set()
    for idx, ch in enumerate(chars):
        if idx in skip:
            continue
        jt = joining_type(ch)
        joined_prev = prev_joins(idx)
        if ch == "ل" and idx + 1 < n and chars[idx + 1] in _ALEF_LIG:
            iso, fin = _ALEF_LIG[chars[idx + 1]]
            results[idx] = (fin if joined_prev else iso, "lamalef")
            skip.add(idx + 1)
            results[idx + 1] = ("", "skip")
            continue
        if jt in ("D", "R"):
            joined_next = out_joined_next[idx]
            if joined_prev and joined_next and jt == "D":
                form = "medial"
            elif joined_prev:
                form = "final"
            elif joined_next and jt == "D":
                form = "initial"
            else:
                form = "isolated"
            results[idx] = (ch, form)
        else:
            results[idx] = (ch, "none")
    return [r for r in results if r is not None]  # type: ignore[misc]


def _glyph_for_form(face: FontFace, ch: str, form: str) -> str | None:
    if form in ("none", "lamalef") or form == "":
        return face.glyph_for_char(ch)
    base_glyph = face.glyph_for_char(ch)
    # ۱) فرم نمایشی یونیکد در cmap
    pf = _FORMS.get(ch, {}).get(form)
    if pf and face.has_char(pf):
        return face.glyph_for_char(pf)
    # ۲) GSUB
    tag = {"initial": "init", "medial": "medi", "final": "fina", "isolated": "isol"}[form]
    if base_glyph:
        g = face.gsub_single(tag, base_glyph)
        if g:
            return g
    return base_glyph


def _apply_ligatures(face: FontFace, glyphs: list[str]) -> list[str]:
    ligs = face.gsub_ligatures(("rlig", "liga", "ccmp"))
    if not ligs:
        return glyphs
    out: list[str] = []
    i = 0
    while i < len(glyphs):
        for comp, lig in ligs:
            if tuple(glyphs[i:i + len(comp)]) == comp and len(comp) > 1:
                out.append(lig)
                i += len(comp)
                break
        else:
            out.append(glyphs[i])
            i += 1
    return out


def shape_run_builtin(face: FontFace, text: str, rtl: bool, warnings: list[str],
                      kerning: bool = True) -> list[ShapedGlyph]:
    """شکل‌دهی یک run؛ خروجی به ترتیب دیداری (چپ به راست)."""
    glyphs: list[ShapedGlyph] = []
    if rtl:
        pairs = _resolve_forms(text)
        items: list[tuple[str, str, bool]] = []  # (نام گلیف, نویسه, علامت؟)
        for ch, form in pairs:
            if form == "skip" or ch in (ZWNJ, ZWJ):
                continue
            if ord(ch) in _HARAKAT:
                g = face.glyph_for_char(ch)
                if g:
                    items.append((g, ch, True))
                continue
            g = _glyph_for_form(face, ch, form)
            if g is None:
                warnings.append(f"گلیف برای U+{ord(ch):04X} در فونت «{face.name}» نیست")
                continue
            items.append((g, ch, False))
        merged = _apply_ligatures(face, [g for g, _, _ in items])
        if len(merged) != len(items):  # لیگاتور اعمال شده؛ علامت‌ها در این حالت پشتیبانی نمی‌شوند
            items = [(g, "", False) for g in merged]
        last_adv = 0.0
        for g, ch, is_mark in items:
            if is_mark:
                glyphs.append(ShapedGlyph(face, g, 0.0, dx=0.5 * last_adv, char=ch))
            else:
                last_adv = face.advance(g)
                glyphs.append(ShapedGlyph(face, g, last_adv, char=ch))
        glyphs.reverse()  # منطقی → دیداری
        return glyphs
    prev = None
    for ch in text:
        if ch in (ZWNJ, ZWJ):
            continue
        g = face.glyph_for_char(ch)
        if g is None:
            if ch.isspace():
                glyphs.append(ShapedGlyph(face, "", 0.25, char=ch))
                prev = None
                continue
            warnings.append(f"گلیف برای U+{ord(ch):04X} در فونت «{face.name}» نیست")
            continue
        adv = face.advance(g)
        if kerning and prev is not None:
            adv_prev = glyphs[-1]
            adv_prev.advance += face.kern(prev, g)
        glyphs.append(ShapedGlyph(face, g, adv, char=ch))
        prev = g
    return glyphs


def shape_run_harfbuzz(face: FontFace, text: str, rtl: bool, warnings: list[str],
                       kerning: bool = True) -> list[ShapedGlyph]:  # pragma: no cover
    blob = hb.Blob.from_file_path(face.path)
    hbface = hb.Face(blob, face.index)
    font = hb.Font(hbface)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.direction = "rtl" if rtl else "ltr"
    if rtl:
        buf.script = "Arab"
        buf.language = "fa"
    else:
        buf.script = "Latn"
        buf.language = "en"
    hb.shape(font, buf, {"kern": kerning, "liga": True, "rlig": True, "calt": True,
                         "init": True, "medi": True, "fina": True, "isol": True, "mark": True, "mkmk": True})
    upem = face.upem
    out = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        name = face.order[info.codepoint] if info.codepoint < len(face.order) else ""
        if name == ".notdef":
            warnings.append(f"گلیف .notdef در فونت «{face.name}»")
        out.append(ShapedGlyph(face, name, pos.x_advance / upem, pos.x_offset / upem,
                               pos.y_offset / upem))
    return out  # HarfBuzz خروجی را همیشه به ترتیب دیداری برمی‌گرداند


def shape_run(face: FontFace, text: str, rtl: bool, warnings: list[str],
              backend: str = "auto", kerning: bool = True) -> list[ShapedGlyph]:
    if backend in ("auto", "harfbuzz") and hb is not None:
        try:
            return shape_run_harfbuzz(face, text, rtl, warnings, kerning)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"HarfBuzz ناموفق بود ({e}); از شکل‌دهنده‌ی داخلی استفاده شد")
    return shape_run_builtin(face, text, rtl, warnings, kerning)


def active_backend() -> str:
    return "harfbuzz" if hb is not None else "builtin"
