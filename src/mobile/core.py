"""هسته‌ی نسخه‌ی موبایل (بدون وابستگی به رابط): بارگذاری قالب PNG/TGS، پیش‌نمایش و تولید ماهانه.

رابط Kivy فقط این کلاس را صدا می‌زند؛ پس منطق روی کامپیوتر تست می‌شود (tests/test_mobile.py)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PIL import Image

from ..calendars.jalali import JALALI_MONTHS_FA, day_info
from ..export.batch import BatchResult, generate_month
from ..png.engine import PNG_MAX_BYTES, RasterEngine, encode_png, generate_month_png
from ..png.session import load_session, stale_slots
from ..render.simple_renderer import Renderer
from ..tgs.analyzer import analyze
from ..tgs.autodetect import detect_best
from ..tgs.lottie_io import dump_tgs_bytes, load_tgs
from ..tgs.replacer import KASHIDA_SLOTS, TemplateEngine, fit_kashida
from ..vector_text.fonts import default_font_path


class Project:
    def __init__(self, fa_font: str | None = None, en_font: str | None = None):
        self.default_font = default_font_path(True)
        self.fa_font = fa_font or self.default_font
        self.en_font = en_font or self.default_font
        self.scale_pct = 100                      # اندازه‌ی کلی نوشته‌ها (٪)
        self.kashida_override: int | None = None  # None = خودکار از روی قالب
        self.kind = ""                            # "png" | "tgs" | ""
        self.name = ""
        self.slots: list = []
        self.base_day = None
        self.doc = None
        self.png = None                           # PngSession
        self.auto_kashida: dict[str, int] = {}
        self.message = "هنوز قالبی انتخاب نشده است."
        self.ok = False

    # ------------------------------------------------------------- قالب
    def load(self, path: str) -> str:
        self.ok = False
        self.name = Path(path).name
        try:
            if path.lower().endswith((".png", ".webp")):
                self._load_png(path)
            else:
                self._load_tgs(path)
        except Exception as e:  # noqa: BLE001
            self.message = f"✘ {e}"
            self.kind = ""
            return self.message
        self.ok = True
        return self.message

    def _load_png(self, path: str):
        ss = load_session(path, self.default_font, self.default_font)
        self.kind, self.png, self.doc = "png", ss, None
        self.slots, self.base_day, self.auto_kashida = ss.slots, ss.base_day, dict(ss.kashida)
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
        self.message = msg

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

    # ------------------------------------------------------------- تنظیمات
    def _apply(self):
        for s in self.slots:
            base = s.name.split(" (کپی")[0]
            s.fa_font, s.en_font = self.fa_font, self.en_font
            s.scale_mul = self.scale_pct / 100.0
            if base in KASHIDA_SLOTS:
                k = self.kashida_override if self.kashida_override is not None else self.auto_kashida.get(base, 0)
                s.kashida = int(k)
            else:
                s.kashida = 0

    def engine(self):
        if not self.ok:
            raise RuntimeError("قالبی بارگذاری نشده است.")
        self._apply()
        if self.kind == "png":
            return RasterEngine(self.png.img, self.png.blobs, self.slots, self.base_day)
        return TemplateEngine(self.doc, self.slots, self.base_day)

    # ------------------------------------------------------------- پیش‌نمایش
    def preview(self, jy: int, jm: int, jd: int = 1, size: int = 512) -> tuple[Image.Image, str]:
        """(تصویر RGBA روی زمینه‌ی سفید، متن وضعیت/حجم)."""
        eng = self.engine()
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
            out = Renderer(doc, size, 1).render((doc.get("ip", 0) + doc.get("op", 60)) / 2.0, bg=None)
        bad = [r for r in reps if not r.ok]
        info = f"{day.jd} {day.jalali_month_fa} {day.jy} · حجم ≈ {kb:.0f}KB از {limit}"
        if bad:
            info += "\n⚠ " + "، ".join(f"{r.slot}: {'; '.join(r.warnings)[:50]}" for r in bad)
        flat = Image.new("RGBA", out.size, (255, 255, 255, 255))
        flat.alpha_composite(out.convert("RGBA"))
        return flat.resize((size, size)) if flat.size != (size, size) and flat.size[0] == flat.size[1] else flat, info

    # ------------------------------------------------------------- تولید ماهانه
    def generate(self, jy: int, jm: int, out_dir: str, progress: Callable[[int, int, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None) -> BatchResult:
        eng = self.engine()
        fn = generate_month_png if self.kind == "png" else generate_month
        return fn(eng, jy, jm, os.path.join(out_dir, f"{jy}-{jm:02d}"), True, progress=progress, cancel=cancel)


MONTHS = list(JALALI_MONTHS_FA)
