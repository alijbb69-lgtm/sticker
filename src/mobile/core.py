"""هسته‌ی نسخه‌ی موبایل (بدون وابستگی به رابط): قالب PNG/TGS، تنظیمات هر متن، پیش‌نمایش، تولید ماهانه و ذخیره‌ی تنظیمات.
رابط Kivy فقط این کلاس را صدا می‌زند؛ پس منطق روی کامپیوتر تست می‌شود (tests/test_mobile.py)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image

from ..calendars.jalali import JALALI_MONTHS_FA, day_info
from ..export.batch import BatchResult, generate_month
from ..png.engine import PNG_MAX_BYTES, RasterEngine, encode_png, generate_month_png
from ..png.session import PngSession, file_hash, load_session, stale_slots
from ..png.setup import apply_assignment, suggest
from ..render.simple_renderer import Renderer
from ..tgs.analyzer import analyze
from ..tgs.autodetect import detect_best
from ..tgs.lottie_io import dump_tgs_bytes, load_tgs
from ..tgs.replacer import KASHIDA_SLOTS, TemplateEngine, fit_kashida
from ..vector_text.fonts import default_font_path

MONTHS = list(JALALI_MONTHS_FA)


class Project:
    def __init__(self, fa_font: str | None = None, en_font: str | None = None):
        self.default_font = default_font_path(True)
        self.fa_font = fa_font or self.default_font
        self.en_font = en_font or self.default_font
        self.slot_fonts: dict[str, str] = {}
        self.sizes: dict[str, int] = {}                  # نام متغیر → ٪
        self.offsets: dict[str, tuple] = {}              # نام متغیر → (dx, dy) پیکسل
        self.kash_user: dict[str, int] = {}
        self.jy, self.jm = 1405, 8
        self.kind = ""                                   # "png" | "tgs" | ""
        self.name = ""
        self.path = ""
        self.slots: list = []
        self.base_day = None
        self.doc = None
        self.png: PngSession | None = None
        self.png_manual = False
        self.auto_kashida: dict[str, int] = {}
        self.message = "هنوز قالبی انتخاب نشده است."
        self.ok = False

    # ------------------------------------------------------------- قالب
    def load(self, path: str, saved_png: dict | None = None) -> str:
        self.ok = False
        self.name = Path(path).name
        try:
            if path.lower().endswith((".png", ".webp")):
                self._load_png(path, saved_png)
            else:
                self._load_tgs(path)
        except Exception as e:  # noqa: BLE001
            self.message = f"✘ {e}"
            self.kind = ""
            return self.message
        self.path = path
        self.ok = True
        return self.message

    def _load_png(self, path: str, saved: dict | None):
        ss = load_session(path, self.default_font, self.default_font, saved)
        self.kind, self.png, self.doc = "png", ss, None
        self.slots, self.base_day, self.auto_kashida = ss.slots, ss.base_day, dict(ss.kashida)
        self.png_manual = not ss.auto
        self.message = self._png_message()

    def _png_message(self) -> str:
        ss = self.png
        msg = f"✔ {self.name} (استیکر ثابت)\n" + "\n".join(ss.notes) + "\nتشخیص: " + ss.summary()
        un = ss.unmapped()
        if un:
            msg += "\n⚠ پیدا نشد (تغییر نمی‌کند): " + "، ".join(un)
        try:
            bad = stale_slots(RasterEngine(ss.img, ss.blobs, ss.slots, ss.base_day), day_info(1405, 8, 1), day_info(1405, 9, 2))
        except Exception:  # noqa: BLE001
            bad = []
        if bad:
            msg += "\n⚠ این متن‌ها با عوض‌شدن تاریخ تغییر نمی‌کنند: " + "، ".join(bad)
        if max(ss.img.size) != 512:
            msg += "\n⚠ استیکر تلگرام باید یک ضلعش دقیقاً ۵۱۲ باشد."
        return msg

    def _load_tgs(self, path: str):
        doc = load_tgs(path)
        cands = analyze(doc)
        slots, det = detect_best(doc, cands, self.default_font, self.default_font)
        if not det.ok:
            raise ValueError(det.message)
        asp = {}
        for s in slots:
            c = next((x for x in cands if x.id == s.candidate_id), None) if s.mapped else None
            if c is not None and c.world_bbox:
                h = c.world_bbox[3] - c.world_bbox[1]
                if h > 1e-6:
                    asp[s.name] = (c.world_bbox[2] - c.world_bbox[0]) / h
        self.auto_kashida = fit_kashida(slots, det.base_day, asp)
        self.kind, self.doc, self.png = "tgs", doc, None
        self.slots, self.base_day = slots, det.base_day
        msg = f"✔ {self.name}\n{det.message}"
        miss = [s.name for s in slots if not s.mapped and not s.name.startswith("روز هفته")]
        if miss:
            msg += "\n⚠ پیدا نشد (تغییر نمی‌کند): " + "، ".join(miss)
        self.message = msg

    # ------------------------------------------------------------- نام متغیرها و PNG
    def slot_names(self) -> list[str]:
        return [s.name for s in self.slots if s.mapped and "(کپی" not in s.name]

    def all_slot_names(self) -> list[str]:
        return [s.name for s in self.slots if "(کپی" not in s.name]

    def png_assign(self) -> dict:
        if not self.png:
            return {}
        return {s.name: (s.candidate_id, s.digits) for s in self.slots if s.mapped}

    def png_base(self) -> tuple:
        d = self.base_day
        return (d.jy, d.jm, d.jd)

    def png_suggest(self, ymd: tuple) -> dict:
        return suggest(self.slots, self.png.pre, day_info(*ymd))

    def png_set(self, assign: dict, ymd: tuple):
        """اصلاح دستی نواحی/تاریخِ نوشته‌شده روی استیکر ثابت."""
        ss = self.png
        apply_assignment(self.slots, {k: tuple(v) for k, v in assign.items()}, ss.cands)
        self.base_day = day_info(*ymd)
        ss.base_day, ss.assign, ss.auto = self.base_day, {k: tuple(v) for k, v in assign.items()}, False
        self.png_manual = True
        self.message = self._png_message()

    # ------------------------------------------------------------- تنظیمات روی اسلات‌ها
    def _apply(self, slots=None):
        for s in (self.slots if slots is None else slots):
            base = s.name.split(" (کپی")[0]
            own = self.slot_fonts.get(base)
            s.fa_font, s.en_font = (own, own) if own else (self.fa_font, self.en_font)
            s.scale_mul = self.sizes.get(base, 100) / 100.0
            s.dx, s.dy = self.offsets.get(base, (0, 0))
            if base in KASHIDA_SLOTS:
                s.kashida = int(self.kash_user.get(base, self.auto_kashida.get(base, 0)))
            else:
                s.kashida = 0

    def kashida_of(self, name: str) -> int:
        return int(self.kash_user.get(name, self.auto_kashida.get(name, 0)))

    def engine(self, isolate: bool = False):
        """isolate=True: روی «کپی» اسلات‌ها کار می‌کند تا رابط هم‌زمان بتواند تنظیمات را عوض کند (پیش‌نمایش در پس‌زمینه)."""
        if not self.ok:
            raise RuntimeError("قالبی بارگذاری نشده است.")
        import copy
        slots = copy.deepcopy(self.slots) if isolate else self.slots
        self._apply(slots)
        if self.kind == "png":
            return RasterEngine(self.png.img, self.png.blobs, slots, self.base_day)
        return TemplateEngine(self.doc, slots, self.base_day)

    def reset_adjustments(self):
        self.sizes, self.offsets, self.kash_user = {}, {}, {}

    # ------------------------------------------------------------- پیش‌نمایش
    def frame_range(self) -> tuple[int, int]:
        if self.kind != "tgs":
            return 0, 0
        return int(self.doc.get("ip", 0)), max(int(self.doc.get("ip", 0)), int(self.doc.get("op", 60)) - 1)

    def preview(self, jy: int | None = None, jm: int | None = None, jd: int = 1, size: int = 512,
                frame: int | None = None) -> tuple[Image.Image, str]:
        """(تصویر RGBA روی زمینه‌ی سفید، متن وضعیت/حجم)."""
        jy, jm = jy or self.jy, jm or self.jm
        eng = self.engine(isolate=True)
        day = day_info(jy, jm, jd)
        if self.kind == "png":
            im, reps = eng.generate(day)
            kb = len(encode_png(im)) / 1024
            limit = PNG_MAX_BYTES // 1024
            out = im
        else:
            doc, reps = eng.generate(day)
            kb = len(dump_tgs_bytes(doc, 2)) / 1024
            limit = 64
            ip, last = self.frame_range()
            f = (ip + last) // 2 if frame is None else max(ip, min(last, frame))
            out = Renderer(doc, size, 1).render(float(f), bg=None)
        bad = [r for r in reps if not r.ok]
        info = f"{day.jd} {day.jalali_month_fa} {day.jy} · حجم ≈ {kb:.0f}KB از {limit}"
        if bad:
            info += "\n⚠ " + "، ".join(f"{r.slot}: {'; '.join(r.warnings)[:50]}" for r in bad)
        flat = Image.new("RGBA", out.size, (255, 255, 255, 255))
        flat.alpha_composite(out.convert("RGBA"))
        return (flat.resize((size, size)) if flat.size != (size, size) and flat.size[0] == flat.size[1] else flat), info

    # ------------------------------------------------------------- تولید ماهانه
    def generate(self, jy: int | None, jm: int | None, out_dir: str,
                 progress: Callable[[int, int, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None) -> BatchResult:
        jy, jm = jy or self.jy, jm or self.jm
        eng = self.engine()
        fn = generate_month_png if self.kind == "png" else generate_month
        return fn(eng, jy, jm, os.path.join(out_dir, f"{jy}-{jm:02d}"), True, progress=progress, cancel=cancel)

    # ------------------------------------------------------------- ذخیره/بازیابی تنظیمات
    def state(self) -> dict:
        st = {"fa": self.fa_font, "en": self.en_font, "over": self.slot_fonts, "sizes": self.sizes,
              "pos": {k: list(v) for k, v in self.offsets.items()}, "kash": self.kash_user,
              "jy": self.jy, "jm": self.jm, "tpl": self.path}
        if self.kind == "png" and self.png_manual and self.png:
            st["png"] = {"hash": self.png.digest, "manual": True,
                         "assign": {k: list(v) for k, v in self.png_assign().items()}, "base": list(self.png_base())}
        return st

    def restore(self, st: dict) -> None:
        ok = lambda p: bool(p) and os.path.exists(p)  # noqa: E731
        if ok(st.get("fa")):
            self.fa_font = st["fa"]
        if ok(st.get("en")):
            self.en_font = st["en"]
        self.slot_fonts = {k: v for k, v in st.get("over", {}).items() if ok(v)}
        self.sizes = {k: int(v) for k, v in st.get("sizes", {}).items()}
        self.offsets = {k: tuple(v) for k, v in st.get("pos", {}).items()}
        self.kash_user = {k: int(v) for k, v in st.get("kash", {}).items()}
        self.jy, self.jm = int(st.get("jy", self.jy)), int(st.get("jm", self.jm))
        if ok(st.get("tpl")):
            self.load(st["tpl"], st.get("png"))


def save_state(proj: Project, path: str, extra: dict | None = None) -> None:
    try:
        st = proj.state()
        st.update(extra or {})
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def load_state(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
