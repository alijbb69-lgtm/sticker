"""تشخیص خودکار تاریخ و جای هر متغیر در یک PNG (همان ایده‌ی تشخیص TGS: رأی‌گیری مشترک روی همه‌ی تاریخ‌های ممکن)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ..calendars.jalali import DayInfo
from ..render.raster import iou, polygons_mask
from ..tgs.autodetect import (Detection, _all_days, _kashida_variants, _silhouette)
from ..tgs.replacer import SlotSpec, _box, _em_polys, render_text, slot_text
from .segment import Cluster, find_clusters

MIN_SLOT_SCORE = 0.52
MIN_MAPPED = 5
MIN_MEAN_SCORE = 0.60
MASK_SIZE = (96, 48)


@dataclass
class StaticField:
    slot: str
    cluster: Cluster
    score: float
    color: tuple


@dataclass
class StaticDetection(Detection):
    fields: dict[str, StaticField] = field(default_factory=dict)
    clusters: list[Cluster] = field(default_factory=list)


def _cluster_mask(c: Cluster) -> np.ndarray:
    h, w = c.mask.shape
    im = Image.fromarray((c.mask * 255).astype("uint8")).resize(MASK_SIZE, Image.BILINEAR)
    return np.asarray(im) > 110


def detect_static(img: Image.Image, slots: list[SlotSpec], years=range(1400, 1411)) -> StaticDetection:
    clusters = find_clusters(img)
    cdat = []
    for c in clusters:
        x0, y0, x1, y1 = c.bbox
        w, h = x1 - x0, y1 - y0
        if w < 6 or h < 6:
            continue
        m = _cluster_mask(c)
        cdat.append((c, m, _silhouette(m), w / h))
    for s in slots:
        s.candidate_id, s.confidence, s.digits = None, 0.0, "keep"
    if not cdat:
        return StaticDetection(False, None, 0, 0.0, "در این تصویر نوشته‌ای پیدا نشد.")

    days = _all_days(years)
    texts = {s.name: {slot_text(s, d) for d in days} for s in slots}
    score: dict[str, dict[str, dict[int, tuple]]] = {}
    for s in slots:
        score[s.name] = {}
        for t in texts[s.name]:
            mixed = any(ch.isalpha() and ord(ch) > 0x600 for ch in t) and any(ch.isascii() and ch.isalpha() for ch in t)
            dirs = ["rtl", "ltr"] if mixed else ["auto"]
            styles = ["keep", "persian"] if (s.digits_hint == "persian" and any(ch.isdigit() for ch in t)) else ["keep"]
            variants = [t] + (_kashida_variants(t) if s.name in ("ماه شمسی", "روز هفته (فارسی)") else [])
            best: dict[int, tuple] = {}
            for tv in variants:
                for d in dirs:
                    for dg in styles:
                        lt = render_text(s, tv, d, dg)
                        sp = _em_polys(lt)
                        sb = _box(sp)
                        if not sb or (sb[2] - sb[0]) < 1e-6 or (sb[3] - sb[1]) < 1e-6:
                            continue
                        sm = polygons_mask(sp, sb, MASK_SIZE)
                        ssil = _silhouette(sm)
                        sasp = (sb[2] - sb[0]) / (sb[3] - sb[1])
                        for ci, (c, cm, csil, casp) in enumerate(cdat):
                            ratio = sasp / casp
                            if not (0.5 <= ratio <= 2.0):
                                continue
                            asp = min(sasp, casp) / max(sasp, casp)
                            ov = max(iou(sm, cm), 0.9 * iou(ssil, csil))
                            total = 0.6 * ov + 0.4 * asp
                            if dg == s.digits_hint and dg != "keep":
                                total += 0.08
                            if ci not in best or total > best[ci][0]:
                                best[ci] = (total, d, dg)
            score[s.name][t] = best

    def assign_for(day: DayInfo):
        entries = []
        for s in slots:
            for ci, (sc, _d, _g) in score[s.name].get(slot_text(s, day), {}).items():
                if sc >= MIN_SLOT_SCORE:
                    entries.append((sc, s.name, ci))
        entries.sort(reverse=True)
        used, got, tot = set(), {}, 0.0
        for sc, name, ci in entries:
            if name in got or ci in used:
                continue
            got[name] = ci
            used.add(ci)
            tot += sc
        return tot, got

    best_day, best_tot, assigned = None, -1.0, {}
    for d in days:
        tot, got = assign_for(d)
        if tot > best_tot:
            best_day, best_tot, assigned = d, tot, got
    if len(assigned) < MIN_MAPPED:
        return StaticDetection(False, None, len(assigned), 0.0,
                               f"فقط {len(assigned)} متغیر در تصویر پیدا شد؛ به‌نظر می‌رسد تصویر نوشته‌ی تاریخ ندارد "
                               "یا شبیه قالب تاریخ نیست.", clusters=[c for c, *_ in cdat])
    fields: dict[str, StaticField] = {}
    per_slot = {}
    for s in slots:
        ci = assigned.get(s.name)
        if ci is None:
            continue
        sc, d, dg = score[s.name][slot_text(s, best_day)][ci]
        c = cdat[ci][0]
        s.candidate_id = f"raster:{ci}"
        s.confidence = sc
        if d in ("rtl", "ltr"):
            s.base_dir = d
        if dg != "keep":
            s.digits = dg
        fields[s.name] = StaticField(s.name, c, sc, c.color)
        per_slot[s.name] = sc
    mean = sum(per_slot.values()) / len(per_slot)
    ok = mean >= MIN_MEAN_SCORE
    msg = (f"تاریخ نوشته‌شده در تصویر: {best_day.jd:02d} {best_day.jalali_month_fa} {best_day.jy} "
           f"({best_day.weekday_en} {best_day.date.day:02d} {best_day.gregorian_month_en[:3].upper()} {best_day.date.year})"
           if ok else "شباهت نوشته‌های تصویر به تاریخ ضعیف است؛ احتمالاً قالب مناسب نیست.")
    return StaticDetection(ok, best_day, len(per_slot), mean, msg, per_slot, fields, [c for c, *_ in cdat])
