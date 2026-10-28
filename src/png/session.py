"""بارگذاری یک قالب PNG (بدون وابستگی به رابط): ناحیه‌یابی، تشخیص خودکار تاریخ و نگاشت، کشیدگی، و خودآزمایی."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from PIL import Image

from ..calendars.jalali import DayInfo, day_info
from ..tgs.autodetect import detect
from ..tgs.replacer import SlotSpec, default_slots, fit_kashida, slot_text
from .blobs import Blob, find_blobs, to_candidates
from .engine import RasterEngine
from .setup import apply_assignment, suggest


def file_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


@dataclass
class PngSession:
    img: Image.Image
    blobs: list[Blob]
    cands: list
    pre: dict
    slots: list[SlotSpec]
    base_day: DayInfo
    assign: dict[str, tuple[str, str]]
    kashida: dict[str, int] = field(default_factory=dict)
    digest: str = ""
    auto: bool = True                  # نگاشت خودکار است (نه اصلاح دستی کاربر)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """هر متغیر ← نوشته‌ی فعلی روی استیکر (برای اینکه کاربر درستیِ تشخیص را ببیند)."""
        parts = []
        for s in self.slots:
            if s.mapped:
                parts.append(f"{s.name}: {slot_text(s, self.base_day)}")
        return " · ".join(parts)

    def unmapped(self) -> list[str]:
        return [s.name for s in self.slots if not s.mapped]


def load_session(path: str, fa_font: str, en_font: str, saved: dict | None = None) -> PngSession:
    """saved: {"hash", "assign", "base"} — فقط وقتی استفاده می‌شود که کاربر آن را دستی اصلاح کرده و فایل همان فایل باشد."""
    img = Image.open(path)
    img.load()
    img = img.convert("RGBA")
    blobs, _m = find_blobs(img)
    if not blobs:
        raise ValueError("در این تصویر نوشته‌ای پیدا نشد.")
    cands, pre = to_candidates(blobs)
    slots = default_slots(fa_font, en_font)
    digest = file_hash(path)
    notes: list[str] = []
    use_saved = bool(saved and saved.get("manual") and saved.get("hash") == digest and saved.get("assign")
                     and all(v[0] in {c.id for c in cands} for v in saved["assign"].values()))
    if use_saved:
        base = day_info(*[int(x) for x in saved["base"]])
        assign = {k: (v[0], v[1]) for k, v in saved["assign"].items()}
        apply_assignment(slots, assign, cands)
        auto = False
    else:
        import datetime as _dt
        from ..calendars.jalali import gregorian_to_jalali
        ty = gregorian_to_jalali(_dt.date.today())[0]
        det = detect(None, cands, slots, years=range(ty - 3, ty + 3), prebuilt=pre)    # حول‌وحوشِ سالِ جاری (۵↔۹ را اشتباه نگیرد)
        auto = True
        if det.ok and det.base_day:
            base = det.base_day
            assign = {s.name: (s.candidate_id, s.digits) for s in slots if s.mapped}
            notes.append(det.message)
        else:
            from ..calendars.jalali import gregorian_to_jalali
            import datetime as _dt
            jy, jm, jd = gregorian_to_jalali(_dt.date.today())
            base = day_info(jy, jm, 1)
            assign = suggest(slots, pre, base)
            apply_assignment(slots, assign, cands)
            notes.append("⚠ تاریخِ نوشته‌شده روی استیکر قطعی تشخیص داده نشد؛ «تعیین نوشته‌ها روی استیکر ثابت» را باز و اصلاح کنید.")
    asp = {}
    for s in slots:
        b = next((x for x in blobs if x.id == s.candidate_id), None) if s.mapped else None
        if b:
            asp[s.name] = (b.bbox[2] - b.bbox[0]) / max(b.bbox[3] - b.bbox[1], 1)
    kash = fit_kashida(slots, base, asp)
    for s in slots:
        s.kashida = kash.get(s.name, 0)
    return PngSession(img, blobs, cands, pre, slots, base, assign, kash, digest, auto, notes)


def stale_slots(engine: RasterEngine, day_a: DayInfo, day_b: DayInfo) -> list[str]:
    """خودآزمایی: متغیرهایی که مقدارشان بین دو روز فرق دارد ولی پیکسل‌هایشان تغییر نمی‌کند (نگاشت اشتباه/ناحیه‌ی بی‌اثر)."""
    import numpy as np
    a, ra = engine.generate(day_a)
    b, rb = engine.generate(day_b)
    xa, xb = np.asarray(a), np.asarray(b)
    bad = []
    for s in engine.slots:
        if s.name not in engine.plans:
            continue
        if slot_text(s, day_a) == slot_text(s, day_b):
            continue
        x0, y0, x1, y1 = engine.plans[s.name][0].bbox
        if np.array_equal(xa[y0:y1, x0:x1], xb[y0:y1, x0:x1]):
            bad.append(s.name)
    return bad
