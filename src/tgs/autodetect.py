"""تشخیص کاملاً خودکار: هم لایه‌ی هر متغیر و هم «تاریخی که در خود قالب نوشته شده».

کاربر نباید تاریخ نمونه را وارد کند. برای هر متغیر همه‌ی مقدارهای ممکن (روز ۱..۳۱، ماه‌ها، سال‌ها،
روزهای هفته) با فونت انتخاب‌شده ساخته و با شکل هر کاندید مقایسه می‌شود؛ سپس تاریخی انتخاب می‌شود که
مجموع شباهت همه‌ی متغیرها را بیشینه کند.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from ..calendars.jalali import DayInfo, day_info, jalali_month_length
from ..render.raster import iou, polygons_mask
from .analyzer import Candidate, candidate_paths, get_comps
from .replacer import SlotSpec, _box, _em_polys, default_slots, default_slots_combined, render_text, slot_text

MIN_SLOT_SCORE = 0.50     # کمترین شباهت برای پذیرفتن یک نگاشت
WEAK_SLOT_SCORE = 0.50    # آستانه‌ی دور دوم (بالاتر از این؛ نگاشت اشتباه روی لوگو بدتر از نگاشت‌نشدن است)
MIN_MISSING = 1           # حداکثر تعداد متغیرِ پیدا‌نشده برای «قالب معتبر»
MIN_MEAN_SCORE = 0.60     # حداقل میانگین شباهت در تاریخ انتخاب‌شده


_TATWEEL = "\u0640"
_DUAL_JOIN = set("بپتثجچحخسشصضطظعغفقکگلمنیئ")
_FA2EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _norm_name(t: str) -> str:
    """نام لایه/متن را برای مقایسه یکسان می‌کند (بدون کشیده، فاصله و تفاوت ارقام و حروف)."""
    return "".join(ch for ch in t.translate(_FA2EN) if ch not in (_TATWEEL, "\u200c", " ", "\u00a0")).casefold()


import re as _re
_GENERIC_NAME = _re.compile(r"^(shapelayer|layer|null|group|outlines|comp|precomp)\d*$")


def _kashida_variants(t: str) -> list[str]:
    """بعضی قالب‌ها نام ماه را با کشیده می‌نویسند («آبـــان»)؛ شکل‌های کشیده‌ی ممکن را هم امتحان می‌کنیم."""
    if not (len(t) >= 3 and all(ord(ch) > 0x600 for ch in t)):
        return []
    out = []
    for i in range(1, len(t) - 1):
        if t[i] in _DUAL_JOIN:
            for k in (3, 2):
                out.append(t[:i + 1] + _TATWEEL * k + t[i + 1:])
    # کشیده بعد از همه‌ی حروف قابل‌اتصال («شـنـبـه»)
    for k in (1, 2):
        v = "".join(ch + (_TATWEEL * k if (j < len(t) - 1 and ch in _DUAL_JOIN) else "")
                    for j, ch in enumerate(t))
        if v != t:
            out.append(v)
    return out


def _thin(m):
    """اسکلت‌سازی Zhang–Suen (برداری)؛ برای مقایسه‌ی شکل مستقل از ضخامت قلم."""
    import numpy as _np
    a = _np.pad(_np.asarray(m, dtype=bool), 1)
    for _ in range(12):
        changed = False
        for step in (0, 1):
            p2, p3, p4, p5 = a[:-2, 1:-1], a[:-2, 2:], a[1:-1, 2:], a[2:, 2:]
            p6, p7, p8, p9 = a[2:, 1:-1], a[2:, :-2], a[1:-1, :-2], a[:-2, :-2]
            c = a[1:-1, 1:-1]
            nb = (p2.astype(int) + p3 + p4 + p5 + p6 + p7 + p8 + p9)
            seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            tr = sum(((~seq[i]) & seq[i + 1]).astype(int) for i in range(8))
            if step == 0:
                cond = (~(p2 & p4 & p6)) & (~(p4 & p6 & p8))
            else:
                cond = (~(p2 & p4 & p8)) & (~(p2 & p6 & p8))
            rm = c & (nb >= 2) & (nb <= 6) & (tr == 1) & cond
            if rm.any():
                a[1:-1, 1:-1] = c & ~rm
                changed = True
        if not changed:
            break
    return a[1:-1, 1:-1]


def runs_of_polys(polys) -> int:
    """تعداد «تکه‌های جداگانه‌ی افقی» (تقریباً تعداد حرف/رقم‌های جدا از هم) در یک مجموعه چندضلعی."""
    iv = sorted((min(x for x, _ in p), max(x for x, _ in p)) for p in polys if p)
    n, end = 0, None
    for a, b in iv:
        if end is None or a > end:
            n += 1
            end = b
        else:
            end = max(end, b)
    return n


# متغیرهایی که تعداد تکه‌های جدایشان قابل اعتماد است (رقم‌ها و حروف لاتینِ جدا)
RUN_STRICT = {"روز شمسی", "روز میلادی", "سال شمسی", "سال میلادی"}
RUN_LOOSE = {"ماه میلادی", "روز هفته (انگلیسی)"}


def runs_penalty(slot_name: str, text_runs: int, blob_runs) -> float:
    if blob_runs is None:
        return 0.0
    d = abs(text_runs - blob_runs)
    if slot_name in RUN_STRICT:
        return 0.35 * min(d, 2)
    if slot_name in RUN_LOOSE:
        return 0.12 * max(0, d - 1) + 0.04 * min(d, 1)
    return 0.0


def _soft(m):
    """ماسک نرم‌شده (برای مقایسه‌ی مقاوم به ضخامتِ قلم؛ تصویرِ PNG فونت متفاوتی دارد)."""
    import numpy as _np
    from PIL import Image as _I, ImageFilter as _F
    im = _I.fromarray((_thin(m) * 255).astype("uint8"), "L").filter(_F.GaussianBlur(2.0))
    a = _np.asarray(im, dtype=_np.float32)
    a -= a.mean()
    n = float(_np.linalg.norm(a))
    return a / n if n > 1e-6 else a


def _silhouette(m):
    """سیلوئت پر (حفره‌ها پر می‌شوند) — برای نوشته‌های توخالی/Outline دوخطی."""
    import numpy as np
    h, w = m.shape
    outside = np.zeros_like(m, dtype=bool)
    stack = [(y, x) for y in range(h) for x in (0, w - 1)] + [(y, x) for x in range(w) for y in (0, h - 1)]
    while stack:
        y, x = stack.pop()
        if outside[y, x] or m[y, x]:
            continue
        outside[y, x] = True
        if y > 0: stack.append((y - 1, x))
        if y < h - 1: stack.append((y + 1, x))
        if x > 0: stack.append((y, x - 1))
        if x < w - 1: stack.append((y, x + 1))
    return ~outside


@dataclass
class Detection:
    ok: bool
    base_day: DayInfo | None
    mapped: int
    mean_score: float
    message: str
    per_slot: dict[str, float] = field(default_factory=dict)


def _all_days(years) -> list[DayInfo]:
    out = []
    for jy in years:
        for jm in range(1, 13):
            for jd in range(1, jalali_month_length(jy, jm) + 1):
                out.append(day_info(jy, jm, jd))
    return out


def detect(doc: dict | None, cands: list[Candidate], slots: list[SlotSpec], years=range(1400, 1411),
           ref_frame: float | None = None, prebuilt: dict | None = None) -> Detection:
    """prebuilt: برای قالب‌های PNG؛ {id: (None, box, mask, aspect, cand)} به‌جای مسیرهای Lottie."""
    comps = get_comps(doc) if doc is not None else {}
    ip, op = (doc.get("ip", 0), doc.get("op", 60)) if doc is not None else (0, 1)
    frame = (ip + op) / 2.0 if ref_frame is None else ref_frame
    for s in slots:
        s.candidate_id, s.members, s.confidence = None, [], 0.0
        s.digits = "keep"

    # ماسک و جعبه‌ی هر کاندید (یک‌بار)
    cdata = {}
    sil_c = {}
    soft_c = {}
    for c in cands:
        if prebuilt is not None:
            if c.id in prebuilt:
                cdata[c.id] = prebuilt[c.id]
                sil_c[c.id] = _silhouette(prebuilt[c.id][2])
                soft_c[c.id] = _soft(prebuilt[c.id][2])
            continue
        polys = candidate_paths(comps[c.comp], comps[c.comp][c.layer_pos], c, frame)
        box = _box(polys)
        if box and (box[2] - box[0]) > 1 and (box[3] - box[1]) > 1:
            cm = polygons_mask(polys, box)
            cdata[c.id] = (polys, box, cm, (box[2] - box[0]) / (box[3] - box[1]), c)
            sil_c[c.id] = _silhouette(cm)
    if not cdata:
        return Detection(False, None, 0, 0.0, "در این قالب هیچ نوشته‌ی Outline شده‌ای پیدا نشد.")

    # کاندیدهای هم‌شکل (سایه/خط دور/نسخه‌ی گرادیان) یک گروه‌اند؛ فقط نماینده‌ی گروه وارد رقابت می‌شود
    twins_of: dict[str, list[Candidate]] = {}
    reps: list[str] = []
    for c in cands:
        if c.id not in cdata:
            continue
        host = next((r for r in reps if _is_twin(cdata[r][4], c)), None)
        if host is None:
            reps.append(c.id)
            twins_of[c.id] = []
        else:
            twins_of[host].append(c)
    cdata = {cid: cdata[cid] for cid in reps}

    days = _all_days(years)
    # مقدارهای یکتای هر متغیر
    texts: dict[str, set[str]] = {s.name: {slot_text(s, d) for d in days} for s in slots}

    # نام‌های «تاریخ‌مانند»: اگر نام لایه یکی از مقدارهای ممکنِ هر متغیری باشد، قابل اعتماد نیست که نامِ
    # مقدار فعلی باشد (نام لایه‌ها اغلب کهنه‌اند)؛ ولی نام‌های غیرتاریخی (تلفن، لوگو…) نشانه‌ی لایه‌ی غیرتاریخی‌اند
    all_norm = {_norm_name(t) for ts in texts.values() for t in ts}
    all_norm_long = [x for x in all_norm if len(x) >= 4]

    # score[slot][text][cand_id] = (امتیاز، جهت، سبک ارقام)
    score: dict[str, dict[str, dict[str, tuple[float, str, str]]]] = {}
    for s in slots:
        score[s.name] = {}
        for t in texts[s.name]:
            mixed = any(ch.isalpha() and ord(ch) > 0x600 for ch in t) and any(ch.isascii() and ch.isalpha() for ch in t)
            dirs = ["rtl", "ltr"] if mixed else ["auto"]
            styles = ["keep", "persian"] if (s.digits_hint == "persian" and any(ch.isdigit() for ch in t)) else ["keep"]
            best: dict[str, tuple[float, str, str]] = {}
            nt = _norm_name(t)
            variants = [t] + (_kashida_variants(t) if s.name in ("ماه شمسی", "روز هفته (فارسی)") else [])
            for tv in variants:
              for d in dirs:
                for dg in styles:
                    lt = render_text(s, tv, d, dg)
                    sp = _em_polys(lt)
                    sb = _box(sp)
                    if not sb or (sb[2] - sb[0]) < 1e-6 or (sb[3] - sb[1]) < 1e-6:
                        continue
                    smask = polygons_mask(sp, sb)
                    ssil = _silhouette(smask)
                    ssoft = _soft(smask) if prebuilt is not None else None
                    sasp = (sb[2] - sb[0]) / (sb[3] - sb[1])
                    n_glyph = sum(1 for g in lt.glyphs if g.contours)
                    n_cont = len(sp)
                    for cid, (_cp, _cb, cmask, casp, c) in cdata.items():
                        ratio = sasp / casp
                        if not (0.45 <= ratio <= 2.0):
                            continue
                        if c.kind == "cluster" and abs(len(c.members) - n_glyph) > 1:
                            continue
                        asp = min(sasp, casp) / max(sasp, casp)
                        cnt = 0.6 if c.n_paths < 0 else 1.0 - abs(n_cont - c.n_paths) / max(n_cont, c.n_paths, 1)
                        ov = max(iou(smask, cmask), 0.9 * iou(ssil, sil_c[cid]))
                        if prebuilt is not None:
                            ov -= runs_penalty(s.name, runs_of_polys(sp), getattr(c, "runs", None))
                        if ssoft is not None:
                            ov = max(ov, float((ssoft * soft_c[cid]).sum()))
                        total = 0.5 * ov + 0.3 * asp + 0.2 * cnt
                        if dg == s.digits_hint and dg != "keep":
                            total += 0.08
                        cn = _norm_name((c.layer_name or "").replace(" Outlines", "").replace("Outlines", ""))
                        if cn and nt:
                            if cn == nt:
                                total += 0.30      # نام لایه دقیقاً همین متن است
                            elif len(nt) >= 4 and nt in cn:
                                total += 0.20      # نام لایه شامل این متن است («شنبهSATURDAY»)
                            elif (not _GENERIC_NAME.match(cn) and cn not in all_norm
                                  and not any(x in cn for x in all_norm_long)):
                                total -= 0.25      # نام لایه غیرتاریخی است (شماره‌تلفن، لوگو …)
                        if cid not in best or total > best[cid][0]:
                            best[cid] = (total, d, dg)
            score[s.name][t] = best

    by_id = {c.id: c for c in cands}
    mk_cache = {c.id: {(c.comp, c.layer_pos, tuple(c.container), m) for m in c.members} for c in cands}

    def assign_for(d: DayInfo) -> tuple[float, dict[str, str]]:
        """نگاشت حریصانه‌ی یک‌به‌یک برای یک تاریخ مشخص؛ (مجموع امتیاز، نگاشت)."""
        entries = []
        for s in slots:
            per = score[s.name].get(slot_text(s, d), {})
            for cid, (sc, _dd, _g) in per.items():
                if sc >= MIN_SLOT_SCORE:
                    entries.append((sc, s.name, cid))
        entries.sort(reverse=True)
        taken: set = set()
        got: dict[str, str] = {}
        tot = 0.0
        for sc, sname, cid in entries:
            if sname in got:
                continue
            mk = mk_cache[cid]
            if mk & taken:
                continue
            taken |= mk
            got[sname] = cid
            tot += sc
        return tot, got

    best_day, best_tot, assigned = None, -1.0, {}
    for d in days:
        tot, got = assign_for(d)
        if tot > best_tot:
            best_day, best_tot, assigned = d, tot, got

    if len(assigned) < len(slots) - MIN_MISSING:
        for s in slots:
            s.candidate_id, s.members = None, []
        return Detection(False, None, len(assigned), 0.0,
                         f"فقط {len(assigned)} از {len(slots)} متغیر در قالب پیدا شد. به‌نظر می‌رسد این قالب "
                         "نوشته‌ی تاریخ ندارد یا اصلاً شبیه قالب تاریخ نیست.")
    # دور دوم: متغیرهای جامانده با آستانه‌ی ملایم‌تر و فقط از کاندیدهای آزاد
    taken_keys = set().union(*[mk_cache[c] for c in assigned.values()]) if assigned else set()
    for s in slots:
        if s.name in assigned:
            continue
        per = score[s.name].get(slot_text(s, best_day), {})
        for cid, (sc, _d, _g) in sorted(per.items(), key=lambda kv: -kv[1][0]):
            if sc >= WEAK_SLOT_SCORE and not (mk_cache[cid] & taken_keys):
                assigned[s.name] = cid
                taken_keys |= mk_cache[cid]
                best_tot += sc
                break
    n = len(assigned)
    mean = best_tot / n

    per_slot = {}
    for s in slots:
        cid = assigned.get(s.name)
        if not cid:
            continue
        sc, d, dg = score[s.name][slot_text(s, best_day)][cid]
        s.bind(by_id[cid], sc)
        per_slot[s.name] = sc
        if d in ("rtl", "ltr"):
            s.base_dir = d
        if dg != "keep":
            s.digits = dg
    _add_twins(slots, assigned, twins_of, mk_cache)
    ok = mean >= MIN_MEAN_SCORE
    msg = (f"تاریخ نوشته‌شده در قالب: {best_day.jd:02d} {best_day.jalali_month_fa} {best_day.jy} "
           f"({best_day.weekday_en} {best_day.date.day:02d} {best_day.gregorian_month_en[:3].upper()} {best_day.date.year})"
           if ok else "شباهت نوشته‌های قالب به تاریخ ضعیف است؛ احتمالاً قالب مناسب نیست.")
    return Detection(ok, best_day, n, mean, msg, per_slot)


def detect_best(doc: dict, cands: list[Candidate], fa_font: str, en_font: str,
                years=range(1400, 1411)) -> tuple[list[SlotSpec], Detection]:
    """هر دو چیدمان رایج را امتحان می‌کند: روز هفته در دو لایه‌ی جدا، یا در یک لایه («شنبه SATURDAY»).

    نسخه‌ی جدا پیش‌فرض است؛ اگر همه‌ی بخش‌هایش پیدا شد همان انتخاب می‌شود.
    """
    sep = default_slots(fa_font, en_font)
    d1 = detect(doc, cands, sep, years)
    if d1.ok and all(s.mapped for s in sep):
        return sep, d1
    com = default_slots_combined(fa_font, en_font)
    d2 = detect(doc, cands, com, years)
    miss1 = sum(1 for s in sep if not s.mapped) if d1.ok else 99
    miss2 = sum(1 for s in com if not s.mapped) if d2.ok else 99
    # ترکیبی فقط وقتی پذیرفته می‌شود که لایه‌ی روز هفته‌اش قطعی باشد (نگاشت اشتباه روی لوگو/شماره بدتر از نگاشت‌نشدن است)
    wk = next((x for x in com if x.mapped and "+" in x.name), None)
    com_sure = d2.ok and (wk is None or wk.confidence >= 0.75)
    if com_sure and miss2 < miss1:
        return com, d2
    return sep, d1


def _is_twin(a: Candidate, b: Candidate) -> bool:
    """b نسخه‌ی تکراری a است (سایه/خط دور/لایه‌ی گرادیان روی همان نوشته): همان ساختار و تقریباً همان جعبه."""
    if a.world_bbox is None or b.world_bbox is None:
        return False
    if a.kind != b.kind or len(a.members) != len(b.members) or a.n_paths != b.n_paths:
        return False
    aw, ah = a.world_bbox[2] - a.world_bbox[0], a.world_bbox[3] - a.world_bbox[1]
    bw, bh = b.world_bbox[2] - b.world_bbox[0], b.world_bbox[3] - b.world_bbox[1]
    if min(aw, ah, bw, bh) < 1:
        return False
    if abs(aw - bw) > 0.06 * max(aw, bw) + 1.5 or abs(ah - bh) > 0.06 * max(ah, bh) + 1.5:
        return False
    acx, acy = (a.world_bbox[0] + a.world_bbox[2]) / 2, (a.world_bbox[1] + a.world_bbox[3]) / 2
    bcx, bcy = (b.world_bbox[0] + b.world_bbox[2]) / 2, (b.world_bbox[1] + b.world_bbox[3]) / 2
    return abs(acx - bcx) <= 14 and abs(acy - bcy) <= 14


def _add_twins(slots: list[SlotSpec], assigned: dict[str, str], twins_of: dict[str, list[Candidate]], mk_cache: dict):
    """هر نوشته در قالب‌های طلایی/سایه‌دار در چند لایه‌ی هم‌شکل است؛ همه‌ی نسخه‌ها باید عوض شوند."""
    import copy
    extra: list[SlotSpec] = []
    for s in list(slots):
        cid = assigned.get(s.name)
        if not cid or not s.mapped:
            continue
        for k, c in enumerate(twins_of.get(cid, []), start=2):
            t = copy.deepcopy(s)
            t.name = f"{s.name} (کپی {k})"
            t.bind(c, s.confidence)
            extra.append(t)
    slots.extend(extra)
