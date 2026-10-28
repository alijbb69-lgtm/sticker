"""اعتبارسنجی فایل‌های TGS نهایی بر اساس محدودیت‌های رسمی تلگرام."""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field

from ..tgs.lottie_io import TGS_MAX_BYTES
from ..tgs.replacer import SlotReport, paths_signature

try:  # رندرر واقعی (در صورت نصب بودن)
    import rlottie_python  # type: ignore
except Exception:  # noqa: BLE001
    rlottie_python = None


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "error"        # error | warn | info

    def __str__(self):
        mark = "✔" if self.ok else ("✘" if self.severity == "error" else "!")
        return f"{mark} {self.name}" + (f" — {self.detail}" if self.detail else "")


@dataclass
class ValidationResult:
    checks: list[Check] = field(default_factory=list)
    size: int = 0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.severity == "error")

    @property
    def errors(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.severity == "error"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.severity == "warn"]

    def add(self, name, ok, detail="", severity="error"):
        self.checks.append(Check(name, bool(ok), detail, severity))


_UNSUPPORTED_SHAPES = {"mm": "Merge Paths", "rp": "Repeater", "sr": "Star", "gs": "Gradient Stroke"}


def _scan(doc: dict, res: ValidationResult):
    found: dict[str, int] = {}

    def bump(k):
        found[k] = found.get(k, 0) + 1

    def walk_layers(layers):
        for l in layers:
            ty = l.get("ty")
            if ty == 5:
                bump("لایه‌ی متنی (Text Layer)")
            if ty == 2:
                bump("لایه‌ی تصویر (Image)")
            if ty == 1:
                bump("لایه‌ی Solid")
            if l.get("ef"):
                bump("افکت لایه")
            if l.get("hasMask") or l.get("masksProperties"):
                bump("ماسک")
            if l.get("ddd") == 1:
                bump("لایه‌ی سه‌بعدی")
            if l.get("ao") == 1:
                bump("Auto-orient")
            if "tm" in l:
                bump("Time Remap")
            walk_shapes(l.get("shapes", []))

    def walk_shapes(items):
        for it in items:
            t = it.get("ty")
            if t in _UNSUPPORTED_SHAPES:
                bump(_UNSUPPORTED_SHAPES[t])
            if t == "gr":
                walk_shapes(it.get("it", []))

    def walk_expr(o):
        if isinstance(o, dict):
            if isinstance(o.get("x"), str):
                bump("Expression")
            for v in o.values():
                walk_expr(v)
        elif isinstance(o, list):
            for v in o:
                walk_expr(v)

    walk_layers(doc.get("layers", []))
    for a in doc.get("assets", []) or []:
        if "layers" in a:
            walk_layers(a["layers"])
    walk_expr(doc)
    hard = {"لایه‌ی متنی (Text Layer)", "لایه‌ی تصویر (Image)", "Expression"}
    for k, n in found.items():
        res.add(f"عدم استفاده از «{k}»", False, f"{n} مورد", "error" if k in hard else "warn")
    if not found:
        res.add("عدم استفاده از ویژگی‌های پشتیبانی‌نشده در تلگرام", True)


def validate_bytes(data: bytes, expectations: list[SlotReport] | None = None,
                   check_render: bool = True) -> ValidationResult:
    res = ValidationResult(size=len(data))
    # ۱) GZIP
    try:
        raw = gzip.decompress(data)
        res.add("فشرده‌سازی GZIP معتبر", True)
    except Exception as e:  # noqa: BLE001
        res.add("فشرده‌سازی GZIP معتبر", False, str(e))
        return res
    # ۲) JSON
    try:
        doc = json.loads(raw.decode("utf-8"))
        res.add("JSON بدون خطا", True)
    except Exception as e:  # noqa: BLE001
        res.add("JSON بدون خطا", False, str(e))
        return res
    # ۳) ساختار Lottie
    missing = [k for k in ("v", "fr", "ip", "op", "w", "h", "layers") if k not in doc]
    ok_struct = not missing and isinstance(doc.get("layers"), list) and all(
        isinstance(l, dict) and "ty" in l for l in doc["layers"])
    res.add("ساختار Lottie (v, fr, ip, op, w, h, layers)", ok_struct, ("فیلدهای ناقص: " + ",".join(missing)) if missing else "")
    if not ok_struct:
        return res
    # ۴-۶) ابعاد، فریم‌ریت، مدت
    res.add("بوم ۵۱۲×۵۱۲", doc["w"] == 512 and doc["h"] == 512, f"{doc['w']}×{doc['h']}")
    fr = float(doc["fr"])
    res.add("نرخ فریم بین ۳۰ تا ۶۰", 30 <= fr <= 60, f"{fr:g} fps")
    dur = (doc["op"] - doc["ip"]) / fr if fr else 999
    res.add("مدت حداکثر ۳ ثانیه", 0 < dur <= 3.0 + 1e-9, f"{dur:.3f} s")
    # ۷) حجم
    res.add("حجم حداکثر ۶۴ کیلوبایت", len(data) <= TGS_MAX_BYTES, f"{len(data)} بایت از {TGS_MAX_BYTES}")
    # ۸) ویژگی‌های ممنوع
    _scan(doc, res)
    # ۹) متن‌های جایگزین‌شده
    if expectations is not None:
        for r in expectations:
            if not r.ok:
                res.add(f"اسلات «{r.slot}»", False, "جایگزینی انجام نشد: " + "; ".join(r.warnings))
                continue
            try:
                n, sig = paths_signature(doc, r.comp, r.layer_pos, r.container, r.members_after)
            except Exception as e:  # noqa: BLE001
                res.add(f"متن «{r.text}» در خروجی", False, f"گروه پیدا نشد: {e}")
                continue
            res.add(f"متن «{r.text}» در خروجی ({r.slot})", n == r.n_paths and sig == r.sig and n > 0,
                    f"{n} مسیر" if n == r.n_paths else f"انتظار {r.n_paths} مسیر، یافت {n}")
    # ۱۰) رندر
    if check_render:
        _render_check(doc, raw, res)
    return res


def _render_check(doc: dict, raw: bytes, res: ValidationResult):
    mid = (doc["ip"] + doc["op"]) / 2
    if rlottie_python is not None:  # pragma: no cover - بسته به نصب
        try:
            anim = rlottie_python.LottieAnimation.from_data(raw.decode("utf-8"))
            img = anim.render_pillow_frame(frame_num=int(mid))
            bbox = img.getbbox()
            res.add("رندر با rlottie", bbox is not None, "تصویر خالی" if bbox is None else "")
            return
        except Exception as e:  # noqa: BLE001
            res.add("رندر با rlottie", False, str(e))
            return
    try:
        from ..render.simple_renderer import render_frame
        img = render_frame(doc, mid, size=128, supersample=1, bg=(0, 0, 0, 0))
        extrema = img.getchannel("A").getextrema()
        res.add("رندر آزمایشی (رندرر داخلی)", extrema[1] > 0, "تصویر کاملاً شفاف" if extrema[1] == 0 else "")
        res.add("آزمایش با rlottie (رندرر تلگرام)", False,
                "rlottie در این محیط نصب نیست؛ این آزمون انجام نشد", "warn")
    except Exception as e:  # noqa: BLE001
        res.add("رندر آزمایشی", False, str(e))
