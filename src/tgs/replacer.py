"""جایگزینی هندسه‌ی متن‌های Outline شده‌ی یک قالب TGS با متن‌های جدید.

اصل کار:
  * هر «اسلات» به یک گروه (یا خوشه‌ی گروه‌ها) در قالب نگاشت می‌شود.
  * فقط آیتم‌های مسیر (sh) آن گروه عوض می‌شود. fill، stroke، trim، transform (جابه‌جایی/مقیاس/چرخش)،
    کی‌فریم‌ها، ماسک‌ها، parent و ترتیب لایه‌ها دست‌نخورده می‌مانند.
  * اندازه و جای متن جدید از روی «متن نمونه‌ی قالب» کالیبره می‌شود تا نیازی به تنظیم دستی نباشد.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any

from ..calendars.jalali import DayInfo
from ..render.raster import iou, polygons_mask
from ..vector_text.engine import (LaidOutText, contours_to_shape_items, layout_text, place_contours)
from ..vector_text.fonts import Contour, FontFace
from .analyzer import (Candidate, candidate_paths, container_items, get_comps, group_matrix)
from .geometry import flatten_path
from .props import IDENTITY, Mat, is_animated, mat_apply, mat_inv, mat_mul
from .props import shape_value_at


# ------------------------------------------------------------------ مدل داده
@dataclass
class SlotSpec:
    name: str
    template: str                         # مثل "{wd_fa} {wd_en}"
    candidate_id: str | None = None
    kind: str = "group"
    comp: str = "root"
    layer_pos: int = 0
    container: list[int] = field(default_factory=list)
    members: list[int] = field(default_factory=list)
    digits: str = "keep"                  # keep | latin | persian | arabic
    digits_hint: str = "keep"             # سبک ارقام محتمل (فقط برای رأی‌گیری در تشخیص خودکار)
    fa_font: str = ""
    en_font: str = ""
    base_dir: str = "auto"                # auto | ltr | rtl
    align: str = "center"                 # left | center | right
    scale_mul: float = 1.0
    dx: float = 0.0
    dy: float = 0.0
    fit: str = "shrink"                   # shrink | none
    max_width_factor: float = 1.0
    tracking: float = 0.0
    line_height: float = 1.25
    color: str | None = None              # "#RRGGBB" یا None = رنگ قالب
    confidence: float = 0.0
    kashida: int = 0                      # کشیدگی (تعداد «ـ» بعد از هر حرفِ قابل‌اتصال)؛ ۰ = بدون کشیدگی

    def bind(self, c: Candidate, confidence: float = 0.0) -> None:
        self.candidate_id, self.kind, self.comp = c.id, c.kind, c.comp
        self.layer_pos, self.container, self.members = c.layer_pos, list(c.container), list(c.members)
        self.confidence = confidence

    @property
    def mapped(self) -> bool:
        return self.candidate_id is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SlotSpec":
        return SlotSpec(**{k: v for k, v in d.items() if k in SlotSpec.__dataclass_fields__})


DEFAULT_SLOTS = [
    ("روز شمسی", "{j_day2}"),
    ("روز میلادی", "{g_day2}"),
    ("روز هفته (فارسی)", "{wd_fa}"),
    ("روز هفته (انگلیسی)", "{wd_en}"),
    ("سال شمسی", "{j_year}"),
    ("ماه شمسی", "{j_month_name}"),
    ("سال میلادی", "{g_year}"),
    ("ماه میلادی", "{g_month_abbr}"),
]


MIN_CONFIDENCE = 0.60   # زیر این مقدار، تشخیص قابل اعتماد نیست


def weak_slots(slots: list[SlotSpec], min_conf: float = MIN_CONFIDENCE) -> list[str]:
    """نام اسلات‌هایی که نگاشت نشده‌اند یا اطمینانشان کم است (مثلاً قالبِ بدون تاریخ)."""
    return [s.name for s in slots if not s.mapped or s.confidence < min_conf]


JALALI_NUMERIC = {"روز شمسی", "سال شمسی"}
COMBINED_WEEKDAY = ("روز هفته (فارسی + انگلیسی)", "{wd_fa} {wd_en}")


def default_slots_combined(fa_font: str, en_font: str) -> list[SlotSpec]:
    """نسخه‌ای که روز هفته‌ی فارسی و انگلیسی در «یک لایه» نوشته شده‌اند (مثل «شنبه SATURDAY»)."""
    items = [(n, t) for n, t in DEFAULT_SLOTS if not n.startswith("روز هفته")]
    items.insert(2, COMBINED_WEEKDAY)
    return [SlotSpec(n, t, fa_font=fa_font, en_font=en_font,
                     digits_hint="persian" if n in JALALI_NUMERIC else "keep") for n, t in items]


def default_slots(fa_font: str, en_font: str) -> list[SlotSpec]:
    return [SlotSpec(n, t, fa_font=fa_font, en_font=en_font,
                     digits_hint="persian" if n in JALALI_NUMERIC else "keep") for n, t in DEFAULT_SLOTS]


class _FontCache:
    def __init__(self):
        self._c: dict[str, FontFace] = {}

    def get(self, path: str) -> FontFace:
        if path not in self._c:
            self._c[path] = FontFace(path)
        return self._c[path]


FONTS = _FontCache()


def render_text(slot: SlotSpec, text: str, direction: str | None = None, digits: str | None = None) -> LaidOutText:
    fa = FONTS.get(slot.fa_font)
    en = FONTS.get(slot.en_font or slot.fa_font)
    return layout_text(text, fa, en, digits=digits or slot.digits, base_dir=direction or slot.base_dir,
                       line_height=slot.line_height, tracking=slot.tracking)


_JOINERS = set("بپتثجچحخسشصضطظعغفقکگلمنیئ")      # حروفی که به حرف بعدی می‌چسبند
KASHIDA_SLOTS = ("روز هفته (فارسی)", "ماه شمسی")      # متغیرهایی که قالب‌ها معمولاً کشیده می‌نویسند


def stretch_text(text: str, k: int) -> str:
    """بعد از هر حرفِ قابل‌اتصال (غیر از آخر هر کلمه) k کشیده می‌گذارد: شنبه → شـنـبـه (k=1)، شـــنـــبـــه (k=3)."""
    if k <= 0:
        return text
    # ZWNJ بعد از حرفِ چسبان («یک‌شنبه») با کشیده جایگزین می‌شود تا حرف‌ها بچسبند؛ در «سه‌شنبه» جدا می‌ماند
    chars = list(text)
    for i, c in enumerate(chars):
        if c == "\u200c" and i > 0 and chars[i - 1] in _JOINERS:
            chars[i] = ""
    text = "".join(chars)
    out = []
    for w in text.replace("\u200c", " \u200c ").split(" "):
        if len(w) >= 3 and all(ord(c) > 0x600 for c in w):
            w = "".join(c + ("\u0640" * k if (i < len(w) - 1 and c in _JOINERS and not (w[i + 1] == "ه" and i + 1 < len(w) - 1))
                             else "") for i, c in enumerate(w))
        out.append(w)
    return " ".join(out).replace(" \u200c ", "\u200c")


def slot_text(slot: SlotSpec, day: DayInfo) -> str:
    t = slot.template.format(**day.fields())
    return stretch_text(t, slot.kashida) if slot.kashida else t


def render_fit(s: SlotSpec, day: DayInfo, K: float, limit: float):
    """متنِ روز را می‌چیند؛ اگر با کشیدگیِ کامل از پهنای مجاز بیرون می‌زد، کشیدگی را کم می‌کند
    (به‌جای کوچک‌کردن حروف): «یکشنبه» از «جمعه» بلندتر است. برمی‌گرداند (متن، LaidOutText)."""
    k0 = s.kashida
    try:
        # کشیدگی تا ۱ پایین می‌آید (نه ۰): همه‌ی روزها کشیده بمانند؛ اگر باز هم جا نشد، موتور کل متن را کوچک می‌کند
        for k in range(k0, max(0, min(k0, 1)) - 1, -1):
            s.kashida = k
            text = slot_text(s, day)
            lt = render_text(s, text)
            bb = lt.bbox()
            if k <= 1 or not bb or limit <= 0 or (bb[2] - bb[0]) * K <= limit:
                return text, lt
    finally:
        s.kashida = k0


def fit_kashida(slots: list[SlotSpec], day: DayInfo, aspects: dict[str, float], max_k: int = 5) -> dict[str, int]:
    """کشیدگی هر متغیر را از روی نسبت پهنا/ارتفاعِ نوشته‌ی قالب حدس می‌زند و روی اسلات می‌گذارد.
    aspects: {نام متغیر: پهنا/ارتفاع نوشته‌ی قالب}. فقط وقتی کشیدگی بهتر از حالت ساده باشد انتخاب می‌شود."""
    import math
    found: dict[str, int] = {}
    for s in slots:
        asp = aspects.get(s.name)
        if not asp or s.name not in KASHIDA_SLOTS or not s.mapped:
            continue
        errs = []
        for k in range(0, max_k + 1):
            s.kashida = k
            try:
                bb = _box(_em_polys(render_text(s, slot_text(s, day))))
            except Exception:  # noqa: BLE001
                bb = None
            if not bb or bb[3] - bb[1] < 1e-6:
                errs.append(9.0)
                continue
            errs.append(abs(math.log(((bb[2] - bb[0]) / (bb[3] - bb[1])) / asp)))
        best = min(range(len(errs)), key=lambda i: errs[i])
        s.kashida = best if (best > 0 and errs[best] < 0.6 * errs[0] and errs[0] > 0.18) else 0
        if s.kashida:
            found[s.name] = s.kashida
    return found


# ------------------------------------------------------------------ تطبیق خودکار
def _em_polys(lt: LaidOutText) -> list[list[tuple[float, float]]]:
    polys = []
    for c in lt.contours():
        p = {"v": [list(v) for v in c.v], "i": [list(v) for v in c.i], "o": [list(v) for v in c.o], "c": True}
        polys.append([(x, -y) for x, y in flatten_path(p, 8)])
    return polys


def _box(polys):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def auto_map(doc: dict, candidates: list[Candidate], slots: list[SlotSpec], base_day: DayInfo,
             ref_frame: float | None = None, threshold: float = 0.40) -> dict[str, list[tuple[str, float]]]:
    """هر اسلات را با شبیه‌ترین کاندید (از نظر شکل حروف، تعداد کانتور و نسبت ابعاد) جفت می‌کند.

    خروجی: برای هر اسلات، فهرست امتیاز کاندیدها (برای نمایش در UI). اسلات‌ها درجا نگاشت می‌شوند.
    """
    comps = get_comps(doc)
    ip, op = doc.get("ip", 0), doc.get("op", 60)
    frame = (ip + op) / 2.0 if ref_frame is None else ref_frame
    cand_data = {}
    for c in candidates:
        layer = comps[c.comp][c.layer_pos]
        polys = candidate_paths(comps[c.comp], layer, c, frame)
        box = _box(polys)
        if not box:
            continue
        cand_data[c.id] = (polys, box)

    scores: dict[tuple[str, str], tuple[float, str, str]] = {}
    for s in slots:
        text = slot_text(s, base_day)
        mixed = any(ch.isalpha() and ord(ch) > 0x600 for ch in text) and any(ch.isascii() and ch.isalpha() for ch in text)
        dirs = ["rtl", "ltr"] if mixed else [s.base_dir]
        has_digit = any(ch.isdigit() for ch in text)
        styles = ["keep", "persian"] if (has_digit and s.digits == "keep") else [s.digits]
        for d, dg in [(d, g) for d in dirs for g in styles]:
            lt = render_text(s, text, d, dg)
            spolys = _em_polys(lt)
            sbox = _box(spolys)
            if not sbox:
                continue
            smask = polygons_mask(spolys, sbox)
            sasp = (sbox[2] - sbox[0]) / max(sbox[3] - sbox[1], 1e-9)
            for cid, (cp, cb) in cand_data.items():
                cmask = polygons_mask(cp, cb)
                casp = (cb[2] - cb[0]) / max(cb[3] - cb[1], 1e-9)
                asp = min(sasp, casp) / max(sasp, casp)
                n1, n2 = len(spolys), len(cp)
                cnt = 1.0 - abs(n1 - n2) / max(n1, n2, 1)
                total = 0.5 * iou(smask, cmask) + 0.3 * asp + 0.2 * cnt
                if dg == s.digits_hint and dg != "keep":
                    total += 0.08   # ارقام فارسی برای تاریخ شمسی؛ فونت قالب ممکن است شکل ارقام را متفاوت کشیده باشد
                key = (s.name, cid)
                if key not in scores or total > scores[key][0]:
                    scores[key] = (total, d, dg)
    # انتخاب حریصانه‌ی یک‌به‌یک
    taken_members: set[tuple[str, int, tuple[int, ...], int]] = set()
    by_id = {c.id: c for c in candidates}

    def member_keys(c: Candidate):
        return {(c.comp, c.layer_pos, tuple(c.container), m) for m in c.members}

    ranking: dict[str, list[tuple[str, float]]] = {s.name: [] for s in slots}
    for (sname, cid), (sc, _d, _g) in scores.items():
        ranking[sname].append((cid, sc))
    for k in ranking:
        ranking[k].sort(key=lambda t: -t[1])
    assigned_slots: set[str] = set()
    for (sname, cid), (sc, d, dg) in sorted(scores.items(), key=lambda kv: -kv[1][0]):
        if sname in assigned_slots or sc < threshold:
            continue
        c = by_id[cid]
        mk = member_keys(c)
        if mk & taken_members:
            continue
        slot = next(x for x in slots if x.name == sname)
        slot.bind(c, sc)
        if d in ("rtl", "ltr") and slot.base_dir == "auto":
            slot.base_dir = d
        if slot.digits == "keep" and dg != "keep":
            slot.digits = dg
        taken_members |= mk
        assigned_slots.add(sname)
    return ranking


# ------------------------------------------------------------------ کالیبراسیون و اعمال
@dataclass
class Plan:
    slot: SlotSpec
    orig_box: tuple[float, float, float, float]       # جعبه‌ی متن اصلی در فضای container
    sample_text: str
    K: float                                          # پیکسل به ازای هر em
    sample_cy_em: float                               # مرکز عمودی جوهر نمونه (em، y رو به بالا)


@dataclass
class SlotReport:
    slot: str
    text: str
    ok: bool
    contours: int = 0
    scale: float = 0.0
    shrunk: bool = False
    warnings: list[str] = field(default_factory=list)
    comp: str = "root"
    layer_pos: int = 0
    container: list[int] = field(default_factory=list)
    members_after: list[int] = field(default_factory=list)
    n_paths: int = 0
    sig: str = ""


class TemplateEngine:
    def __init__(self, doc: dict, slots: list[SlotSpec], base_day: DayInfo, ref_frame: float | None = None):
        self.doc = doc
        self.slots = slots
        self.base_day = base_day
        ip, op = doc.get("ip", 0), doc.get("op", 60)
        self.frame = (ip + op) / 2.0 if ref_frame is None else ref_frame
        self.plans: dict[str, Plan] = {}
        self.setup_warnings: list[str] = []
        self.plan_errors: dict[str, str] = {}
        for s in slots:
            if s.mapped:
                try:
                    self.plans[s.name] = self._make_plan(s)
                except Exception as e:  # noqa: BLE001
                    self.plan_errors[s.name] = str(e)
                    self.setup_warnings.append(f"کالیبراسیون «{s.name}» ناموفق: {e}")

    # ---- کالیبراسیون
    def _members(self, doc: dict, s: SlotSpec) -> list[dict]:
        layer = get_comps(doc)[s.comp][s.layer_pos]
        items = container_items(layer, s.container)
        return [items[i] for i in s.members]

    def _make_plan(self, s: SlotSpec) -> Plan:
        comps = get_comps(self.doc)
        layer = comps[s.comp][s.layer_pos]
        cand = Candidate(s.candidate_id or "", s.kind, s.comp, s.layer_pos, layer.get("nm", ""),
                         list(s.container), list(s.members))
        polys = candidate_paths(comps[s.comp], layer, cand, self.frame)
        box = _box(polys)
        if not box:
            raise ValueError("مسیری در لایه‌ی انتخاب‌شده نیست")
        sample = slot_text(s, self.base_day)
        lt = render_text(s, sample)
        em = lt.bbox()
        if not em:
            raise ValueError("متن نمونه گلیفی تولید نکرد: " + "; ".join(lt.warnings))
        h_em = em[3] - em[1]
        h_px = box[3] - box[1]
        K = h_px / h_em if h_em > 1e-9 else (box[2] - box[0]) / max(em[2] - em[0], 1e-9)
        K *= s.scale_mul
        return Plan(s, box, sample, K, (em[1] + em[3]) / 2.0)

    # ---- محاسبه‌ی هندسه
    def _place(self, plan: Plan, lt: LaidOutText) -> tuple[list[list[Contour]], float, bool]:
        s = plan.slot
        bb = lt.bbox()
        if not bb:
            return [], 0.0, False
        ox0, oy0, ox1, oy1 = plan.orig_box
        scale = plan.K
        shrunk = False
        w_px = (bb[2] - bb[0]) * scale
        limit = (ox1 - ox0) * s.max_width_factor * max(1.0, s.scale_mul)
        if s.fit == "shrink" and w_px > limit > 0:
            scale *= limit / w_px
            shrunk = True
        cy = (oy0 + oy1) / 2.0 + s.dy
        baseline = cy + plan.sample_cy_em * scale  # (y رو به پایین)
        if s.align == "left":
            tx = ox0 - bb[0] * scale
        elif s.align == "right":
            tx = ox1 - bb[2] * scale
        else:
            tx = (ox0 + ox1) / 2.0 - (bb[0] + bb[2]) / 2.0 * scale
        tx += s.dx
        glyphs = [place_contours(g.contours, scale, tx, baseline) for g in lt.glyphs if g.contours]
        return glyphs, scale, shrunk

    # ---- تولید برای یک روز
    def generate(self, day: DayInfo, nd: int = 2) -> tuple[dict, list[SlotReport]]:
        doc = copy.deepcopy(self.doc)
        reports: list[SlotReport] = []
        # اسلات‌ها را به ترتیب نزولی اندیس اعضا پردازش می‌کنیم تا حذف/افزودن گروه، اندیس‌های بعدی را خراب نکند
        order = sorted((s for s in self.slots if s.mapped and s.name in self.plans),
                       key=lambda s: (s.comp, s.layer_pos, s.container, -(s.members[0] if s.members else 0)),
                       reverse=False)
        for s in self.slots:   # متغیر نگاشت‌شده‌ای که کالیبره نشد (مثلاً فونت حرف‌ها را ندارد) نباید بی‌صدا رد شود
            if s.mapped and s.name not in self.plans:
                reports.append(SlotReport(s.name, slot_text(s, day), False,
                                          warnings=["کالیبراسیون ناموفق: " + self.plan_errors.get(s.name, "نامشخص")]))
        for s in order:
            plan = self.plans[s.name]
            ox0, _oy0, ox1, _oy1 = plan.orig_box
            text, lt = render_fit(s, day, plan.K, (ox1 - ox0) * s.max_width_factor * max(1.0, s.scale_mul))
            rep = SlotReport(s.name, text, False)
            try:
                rep.warnings += lt.warnings
                glyphs, scale, shrunk = self._place(plan, lt)
                if not glyphs:
                    rep.warnings.append("متن خالی یا بدون گلیف")
                    reports.append(rep)
                    continue
                self._apply(doc, s, glyphs, nd, rep)
                rep.comp, rep.layer_pos, rep.container = s.comp, s.layer_pos, list(s.container)
                rep.n_paths, rep.sig = paths_signature(doc, s.comp, s.layer_pos, s.container, rep.members_after)
                rep.ok = True
                rep.scale, rep.shrunk = scale, shrunk
                rep.contours = sum(len(g) for g in glyphs)
            except Exception as e:  # noqa: BLE001
                rep.warnings.append(f"خطا: {e}")
            reports.append(rep)
        return doc, reports

    # ---- اعمال روی JSON
    def _apply(self, doc: dict, s: SlotSpec, glyphs: list[list[Contour]], nd: int, rep: SlotReport):
        layer = get_comps(doc)[s.comp][s.layer_pos]
        items = container_items(layer, s.container)
        if s.kind == "group" or len(s.members) == 1:
            g = items[s.members[0]]
            flat = [c for gl in glyphs for c in gl]
            self._set_paths(g, flat, nd, rep)
            self._recolor(g, s.color)
            rep.members_after = [s.members[0]]
            return
        # خوشه: هر حرف ↔ یک گروه (به ترتیب چپ به راست)
        members = [items[i] for i in s.members]
        mats = [group_matrix(g, self.frame) for g in members]
        centers = []
        for g, m in zip(members, mats):
            xs = []
            for it in g.get("it", []):
                if it.get("ty") == "sh":
                    v = shape_value_at(it.get("ks", {}), self.frame)
                    if v:
                        xs += [mat_apply(m, x, y)[0] for x, y in v["v"]]
            centers.append(sum(xs) / len(xs) if xs else 0.0)
        order = sorted(range(len(members)), key=lambda k: centers[k])   # چپ به راست
        n, m_cnt = len(order), len(glyphs)
        # (اندیس اصلی در items یا None برای کپی، گروه، ماتریس)
        used: list[tuple[int | None, dict, Mat]] = []
        for k in range(m_cnt):
            if k < n:
                gi = order[k]
                used.append((s.members[gi], members[gi], mats[gi]))
            else:  # حرف بیشتر از گروه‌های قالب: گروه آخر کپی می‌شود (همان انیمیشن)
                _, last_g, last_m = used[-1]
                used.append((None, copy.deepcopy(last_g), last_m))
                rep.warnings.append("تعداد حروف بیشتر از گروه‌های قالب است؛ گروه آخر کپی شد")
        for (_idx, g, m), gl in zip(used, glyphs):
            inv = mat_inv(m)
            self._set_paths(g, [_apply_mat_contour(c, inv) for c in gl], nd, rep)
            self._recolor(g, s.color)
        # جایگزینی ناحیه‌ی اعضا در لیست: ترتیب اصلی (z-order) برای گروه‌های موجود حفظ می‌شود
        originals = sorted((u for u in used if u[0] is not None), key=lambda u: u[0])
        clones = [u for u in used if u[0] is None]
        first = min(s.members)
        for idx in sorted(s.members, reverse=True):
            del items[idx]
        for k, (_i, g, _m) in enumerate(originals + clones):
            items.insert(first + k, g)
        rep.members_after = list(range(first, first + len(used)))

    @staticmethod
    def _set_paths(group: dict, contours: list[Contour], nd: int, rep: SlotReport):
        its = group["it"]
        first = next((i for i, it in enumerate(its) if it.get("ty") == "sh"), len(its))
        if any(it.get("ty") == "sh" and is_animated(it.get("ks")) for it in its):
            rep.warnings.append("مسیرهای قالب کی‌فریم داشتند (مورف)؛ با مسیر ثابت جایگزین شدند. "
                                "ترنسفورم و انیمیشن‌های گروه حفظ شده‌اند.")
        kept = [it for it in its if it.get("ty") != "sh"]
        before = [it for it in its[:first] if it.get("ty") != "sh"]
        new_items = contours_to_shape_items(contours, nd=nd)
        group["it"] = before + new_items + kept[len(before):]

    @staticmethod
    def _recolor(group: dict, color: str | None):
        if not color:
            return
        r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        for it in group.get("it", []):
            if it.get("ty") in ("fl", "st"):
                it["c"] = {"a": 0, "k": [r, g, b, 1], "ix": 4 if it["ty"] == "fl" else 3}


def _apply_mat_contour(c: Contour, m: Mat) -> Contour:
    return Contour([mat_apply(m, x, y) for x, y in c.v],
                   [(m[0] * x + m[2] * y, m[1] * x + m[3] * y) for x, y in c.i],
                   [(m[0] * x + m[2] * y, m[1] * x + m[3] * y) for x, y in c.o])


def paths_signature(doc: dict, comp: str, layer_pos: int, container: list[int],
                    members: list[int]) -> tuple[int, str]:
    """(تعداد مسیرها، امضای SHA-1 رأس‌ها) برای گروه‌های داده‌شده؛ برای اعتبارسنجی خروجی."""
    import hashlib
    layer = get_comps(doc)[comp][layer_pos]
    items = container_items(layer, container)
    h = hashlib.sha1()
    n = 0
    for gi in members:
        for it in items[gi].get("it", []):
            if it.get("ty") == "sh":
                val = shape_value_at(it.get("ks", {}), 0)
                if not val:
                    continue
                n += 1
                h.update(repr([[round(float(a), 2) for a in pt] for pt in val["v"]]).encode())
                h.update(repr([[round(float(a), 2) for a in pt] for pt in val["i"]]).encode())
                h.update(repr([[round(float(a), 2) for a in pt] for pt in val["o"]]).encode())
    return n, h.hexdigest()[:16]
