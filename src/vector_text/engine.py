"""موتور متن برداری: متن → مسیرهای Bézier (فرمت Lottie)."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..calendars.jalali import convert_digits
from .fonts import Contour, FontFace
from .shaping import ShapedGlyph, shape_run, split_runs

_LATIN_DIGITS = set("0123456789")


@dataclass
class LaidOutGlyph:
    contours: list[Contour]
    x0: float
    x1: float
    char: str = ""


@dataclass
class LaidOutText:
    glyphs: list[LaidOutGlyph] = field(default_factory=list)   # به ترتیب دیداری، چپ به راست
    warnings: list[str] = field(default_factory=list)
    base_rtl: bool = False

    def contours(self) -> list[Contour]:
        return [c for g in self.glyphs for c in g.contours]

    def bbox(self) -> tuple[float, float, float, float] | None:
        boxes = [c.bbox() for c in self.contours()]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))


def _pick_face(kind_chars: str, kind: str, fa: FontFace, en: FontFace) -> FontFace:
    if kind == "R":
        return fa
    if kind == "L":
        return en
    # عدد: ارقام فارسی/عربی با فونت فارسی، ارقام لاتین با فونت انگلیسی
    return en if all(c in _LATIN_DIGITS or not c.isdigit() for c in kind_chars) else fa


def _layout_line(text: str, fa: FontFace, en: FontFace, base_dir: str, tracking: float,
                 warnings: list[str], backend: str) -> tuple[list[LaidOutGlyph], float, bool]:
    runs, base_rtl = split_runs(text, base_dir)
    pen = 0.0
    out: list[LaidOutGlyph] = []
    for run in runs:
        face = _pick_face(run.text, run.kind, fa, en)
        # اگر فونت انتخابی حرف را ندارد، از فونت دیگر کمک بگیر
        missing = [c for c in run.text if not c.isspace() and c not in "‌‍"
                   and not face.has_char(c) and not (run.kind == "R" and _has_form(face, c))]
        if missing:
            other = en if face is fa else fa
            if all(other.has_char(c) for c in missing) or not all(face.has_char(c) for c in run.text):
                if sum(other.has_char(c) for c in run.text) > sum(face.has_char(c) for c in run.text):
                    face = other
        shaped = shape_run(face, run.text, run.kind == "R", warnings, backend)
        latin_run = run.kind != "R"
        for sg in shaped:
            x = pen + sg.dx
            cs = [c.transformed(1.0, 1.0, x, sg.dy) for c in face.contours(sg.glyph)] if sg.glyph else []
            out.append(LaidOutGlyph(cs, pen, pen + sg.advance, sg.char))
            pen += sg.advance + (tracking if latin_run and sg.advance > 0 else 0.0)
    return out, pen, base_rtl


def _has_form(face: FontFace, ch: str) -> bool:
    from .shaping import _FORMS
    fs = _FORMS.get(ch, {})
    return any(face.has_char(f) for f in fs.values())


def layout_text(text: str, fa_face: FontFace, en_face: FontFace | None = None, *,
                digits: str = "keep", base_dir: str = "auto", line_height: float = 1.25,
                tracking: float = 0.0, line_align: str = "center",
                backend: str = "auto") -> LaidOutText:
    """متن (چندخطی با \\n) را به مسیرهای برداری تبدیل می‌کند.

    مختصات خروجی: em، مبدأ = ابتدای خط‌پایه‌ی خط اول، محور y رو به بالا.
    """
    en_face = en_face or fa_face
    if digits != "keep":
        text = convert_digits(text, digits)
    result = LaidOutText()
    lines = text.split("\n")
    laid: list[tuple[list[LaidOutGlyph], float]] = []
    for ln in lines:
        glyphs, width, base_rtl = _layout_line(ln, fa_face, en_face, base_dir, tracking,
                                               result.warnings, backend)
        result.base_rtl = result.base_rtl or base_rtl
        laid.append((glyphs, width))
    max_w = max((w for _, w in laid), default=0.0)
    for li, (glyphs, width) in enumerate(laid):
        shift = {"left": 0.0, "right": max_w - width}.get(line_align, (max_w - width) / 2)
        dy = -li * line_height
        for g in glyphs:
            g.contours = [c.transformed(1.0, 1.0, shift, dy) for c in g.contours]
            g.x0 += shift
            g.x1 += shift
            result.glyphs.append(g)
    return result


# ---------------------------------------------------------------- Lottie
def _r(v: float, nd: int) -> float:
    x = round(v, nd)
    return int(x) if x == int(x) else x


def contour_to_lottie(c: Contour, nd: int = 2) -> dict:
    """Contour (y رو به پایین از قبل اعمال‌شده) → دیکشنری مسیر Lottie."""
    return {"i": [[_r(x, nd), _r(y, nd)] for x, y in c.i],
            "o": [[_r(x, nd), _r(y, nd)] for x, y in c.o],
            "v": [[_r(x, nd), _r(y, nd)] for x, y in c.v],
            "c": True}


def contours_to_shape_items(contours: list[Contour], *, nd: int = 2, name_prefix: str = "glyph",
                            start_ind: int = 0) -> list[dict]:
    """لیست آیتم‌های Lottie از نوع «sh» (مسیر) برای قرار گرفتن داخل یک گروه."""
    items = []
    for k, c in enumerate(contours):
        items.append({"ty": "sh", "ix": start_ind + k + 1, "ind": start_ind + k,
                      "ks": {"a": 0, "k": contour_to_lottie(c, nd), "ix": 2},
                      "nm": f"{name_prefix} {k + 1}", "mn": "ADBE Vector Shape - Group", "hd": False})
    return items


def place_contours(contours: list[Contour], scale: float, tx: float, ty: float) -> list[Contour]:
    """em با y رو به بالا → فضای Lottie (y رو به پایین): X = tx + x·scale ، Y = ty − y·scale."""
    return [c.transformed(scale, -scale, tx, ty) for c in contours]
