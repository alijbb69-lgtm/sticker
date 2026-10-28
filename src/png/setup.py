"""راه‌اندازی قالب PNG: پیشنهاد خودکارِ «کدام ناحیه کدام متن است» برای تاریخی که روی استیکر نوشته شده."""
from __future__ import annotations

from ..calendars.jalali import DayInfo
from ..render.raster import iou, polygons_mask
from ..tgs.autodetect import _kashida_variants, _silhouette, _soft, runs_of_polys, runs_penalty
from ..tgs.replacer import SlotSpec, _box, _em_polys, render_text, slot_text

MIN_SUGGEST = 0.42


def suggest(slots: list[SlotSpec], prebuilt: dict, day: DayInfo, debug=False) -> dict[str, tuple[str, str]]:
    """{نام اسلات: (id ناحیه، سبک ارقام)} — نگاشت حریصانه‌ی یک‌به‌یک با شباهت شکل/نسبت ابعاد."""
    sil = {cid: _silhouette(v[2]) for cid, v in prebuilt.items()}
    soft = {cid: _soft(v[2]) for cid, v in prebuilt.items()}
    entries = []
    for s in slots:
        text = slot_text(s, day)
        styles = ["keep", "persian"] if any(ch.isdigit() for ch in text) else ["keep"]
        mixed = any(ch.isalpha() and ord(ch) > 0x600 for ch in text) and any(ch.isascii() and ch.isalpha() for ch in text)
        variants = [text] + (_kashida_variants(text) if s.name in ("ماه شمسی", "روز هفته (فارسی)") else [])
        for dg, text in [(d, t) for d in styles for t in variants]:
            try:
                lt = render_text(s, text, "rtl" if mixed else "auto", dg)
                sp = _em_polys(lt)
                sb = _box(sp)
                if not sb or sb[2] - sb[0] < 1e-6 or sb[3] - sb[1] < 1e-6:
                    continue
                smask = polygons_mask(sp, sb)
            except Exception:  # noqa: BLE001
                continue
            ssil = _silhouette(smask)
            ssoft = _soft(smask)
            sasp = (sb[2] - sb[0]) / (sb[3] - sb[1])
            for cid, (_p, _b, cmask, casp, _c) in prebuilt.items():
                if not (0.5 <= sasp / casp <= 2.0):
                    continue
                asp = min(sasp, casp) / max(sasp, casp)
                ov = max(iou(smask, cmask), 0.9 * iou(ssil, sil[cid]), float((ssoft * soft[cid]).sum()))
                ov -= runs_penalty(s.name, runs_of_polys(sp), getattr(prebuilt[cid][4], "runs", None))
                entries.append((0.6 * ov + 0.4 * asp, s.name, cid, dg))
    entries.sort(reverse=True)
    if debug:
        for e in entries[:30]:
            print(round(e[0], 3), e[1:])
    out: dict[str, tuple[str, str]] = {}
    used: set[str] = set()
    for sc, name, cid, dg in entries:
        if sc < MIN_SUGGEST or name in out or cid in used:
            continue
        out[name] = (cid, dg)
        used.add(cid)
    return out


def apply_assignment(slots: list[SlotSpec], assign: dict[str, tuple[str, str]], cands: list) -> None:
    by = {c.id: c for c in cands}
    for s in slots:
        s.candidate_id, s.members, s.confidence = None, [], 0.0
        if s.name in assign and assign[s.name][0] in by:
            cid, dg = assign[s.name]
            s.bind(by[cid], 1.0)
            s.digits = dg
