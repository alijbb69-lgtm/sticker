"""بارگذاری فونت و استخراج مسیرهای Bézier (مکعبی) از گلیف‌ها با fontTools."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTCollection, TTFont

Point = tuple[float, float]


@dataclass
class Contour:
    """یک مسیر بسته. مختصات بر حسب em (۱ = اندازه‌ی فونت) و محور y رو به بالا.

    فرمت v/i/o همان فرمت Lottie است: i و o نسبت به رأس (نسبی) هستند.
    """
    v: list[Point] = field(default_factory=list)
    i: list[Point] = field(default_factory=list)
    o: list[Point] = field(default_factory=list)

    def transformed(self, sx: float, sy: float, tx: float, ty: float) -> "Contour":
        return Contour([(x * sx + tx, y * sy + ty) for x, y in self.v],
                       [(x * sx, y * sy) for x, y in self.i],
                       [(x * sx, y * sy) for x, y in self.o])

    def bbox(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        n = len(self.v)
        for k in range(n):
            vx, vy = self.v[k]
            xs += [vx, vx + self.i[k][0], vx + self.o[k][0]]
            ys += [vy, vy + self.i[k][1], vy + self.o[k][1]]
        return min(xs), min(ys), max(xs), max(ys)


class _ContourPen(BasePen):
    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self.contours: list[Contour] = []
        self._start: Point | None = None
        self._segs: list[tuple[Point | None, Point | None, Point]] = []

    def _moveTo(self, pt):
        self._start = pt
        self._segs = []

    def _lineTo(self, pt):
        self._segs.append((None, None, pt))

    def _curveToOne(self, c1, c2, pt):
        self._segs.append((c1, c2, pt))

    def _closePath(self):
        self._finish()

    def _endPath(self):
        self._finish()

    def _finish(self):
        if self._start is None or not self._segs:
            self._start = None
            return
        start = self._start
        segs = list(self._segs)
        closes_on_start = segs[-1][2] == start
        n = len(segs) if closes_on_start else len(segs) + 1
        verts = [start] + [s[2] for s in segs[: n - 1]]
        i_t = [(0.0, 0.0)] * n
        o_t = [(0.0, 0.0)] * n
        for k, (c1, c2, end) in enumerate(segs):
            a = verts[k]
            b = verts[(k + 1) % n] if k + 1 < n else start
            if c1 is not None:
                o_t[k] = (c1[0] - a[0], c1[1] - a[1])
                i_t[(k + 1) % n] = (c2[0] - b[0], c2[1] - b[1])
        self.contours.append(Contour(list(verts), list(i_t), list(o_t)))
        self._start = None
        self._segs = []


class FontFace:
    """یک فونت TTF/OTF (یا یک عضو از TTC) با کش گلیف‌ها."""

    def __init__(self, path: str | os.PathLike, index: int = 0):
        self.path = str(path)
        self.index = index
        if self.path.lower().endswith((".ttc", ".otc")):
            self.font = TTCollection(self.path).fonts[index]
        else:
            self.font = TTFont(self.path, lazy=False)
        self.upem = float(self.font["head"].unitsPerEm)
        self.cmap = self.font.getBestCmap() or {}
        self.glyph_set = self.font.getGlyphSet()
        self.hmtx = self.font["hmtx"].metrics
        self.order = self.font.getGlyphOrder()
        self._cache: dict[str, list[Contour]] = {}
        self._kern: dict[tuple[str, str], int] | None = None
        self._gsub_single: dict[str, list[dict[str, str]]] | None = None
        self._gsub_lig: dict[str, list[tuple[tuple[str, ...], str]]] | None = None
        self.name = self._family_name()

    def _family_name(self) -> str:
        try:
            return self.font["name"].getBestFamilyName() or Path(self.path).stem
        except Exception:
            return Path(self.path).stem

    # ---- گلیف‌ها
    def has_char(self, ch: str) -> bool:
        return ord(ch) in self.cmap

    def glyph_for_char(self, ch: str) -> str | None:
        return self.cmap.get(ord(ch))

    def advance(self, glyph: str) -> float:
        return self.hmtx.get(glyph, (0, 0))[0] / self.upem

    def contours(self, glyph: str) -> list[Contour]:
        """مسیرهای گلیف بر حسب em با محور y رو به بالا (گلیف‌های مرکب باز می‌شوند)."""
        if glyph not in self._cache:
            pen = _ContourPen(self.glyph_set)
            if glyph in self.glyph_set:
                self.glyph_set[glyph].draw(pen)
            k = 1.0 / self.upem
            self._cache[glyph] = [c.transformed(k, k, 0.0, 0.0) for c in pen.contours]
        return self._cache[glyph]

    # ---- kern قدیمی
    def kern(self, left: str, right: str) -> float:
        if self._kern is None:
            self._kern = {}
            if "kern" in self.font:
                for t in self.font["kern"].kernTables:
                    self._kern.update(getattr(t, "kernTable", {}))
        return self._kern.get((left, right), 0) / self.upem

    # ---- GSUB (برای شکل‌دهی جایگزین)
    def _load_gsub(self):
        self._gsub_single, self._gsub_lig = {}, {}
        if "GSUB" not in self.font:
            return
        gsub = self.font["GSUB"].table
        if not gsub.FeatureList or not gsub.LookupList:
            return
        for fr in gsub.FeatureList.FeatureRecord:
            tag = fr.FeatureTag
            for li in fr.Feature.LookupListIndex:
                lookup = gsub.LookupList.Lookup[li]
                for st in lookup.SubTable:
                    if lookup.LookupType == 7:
                        st = st.ExtSubTable
                        ltype = st.LookupType
                    else:
                        ltype = lookup.LookupType
                    if ltype == 1 and hasattr(st, "mapping"):
                        self._gsub_single.setdefault(tag, []).append(dict(st.mapping))
                    elif ltype == 4 and hasattr(st, "ligatures"):
                        for first, ligs in st.ligatures.items():
                            for lg in ligs:
                                self._gsub_lig.setdefault(tag, []).append(
                                    (tuple([first] + list(lg.Component)), lg.LigGlyph))

    def gsub_single(self, tag: str, glyph: str) -> str | None:
        if self._gsub_single is None:
            self._load_gsub()
        for m in self._gsub_single.get(tag, []):
            if glyph in m:
                return m[glyph]
        return None

    def gsub_ligatures(self, tags: tuple[str, ...]) -> list[tuple[tuple[str, ...], str]]:
        if self._gsub_lig is None:
            self._load_gsub()
        out: list[tuple[tuple[str, ...], str]] = []
        for t in tags:
            out += self._gsub_lig.get(t, [])
        out.sort(key=lambda x: -len(x[0]))  # طولانی‌ترین تطبیق اول
        return out


def system_font_dirs() -> list[str]:
    dirs = []
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(windir, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    else:
        dirs += ["/system/fonts", "/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                 os.path.expanduser("~/.local/share/fonts"), "/Library/Fonts"]
    return [d for d in dirs if os.path.isdir(d)]


def bundled_font_dir() -> str:
    root = Path(__file__).resolve().parents[2]
    return str(root / "assets" / "fonts")


def default_font_path(bold: bool = False) -> str:
    """فونت پیش‌فرض همراه برنامه (DejaVu Sans، دارای حروف فارسی و لاتین)."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    p = Path(bundled_font_dir()) / name
    if p.exists():
        return str(p)
    raise FileNotFoundError(f"فونت پیش‌فرض پیدا نشد: {p}")


def list_font_files() -> list[str]:
    out = []
    for d in [bundled_font_dir()] + system_font_dirs():
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".ttf", ".otf")):
                    out.append(os.path.join(root, f))
    return sorted(set(out))
