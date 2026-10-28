"""موتور استیکر ثابت (PNG): نوشته‌ی قدیمی پاک می‌شود (بازسازی زمینه از اطراف) و نوشته‌ی جدید با فونت انتخابی کشیده می‌شود.

قالب PNG برداری نیست؛ بنابراین: (۱) کاربر مشخص می‌کند کدام ناحیه‌ها کدام متن‌اند و تاریخِ نوشته‌شده روی استیکر چیست،
(۲) هر ناحیه با «انتشار رنگ از لبه‌ها» (inpainting) پاک می‌شود — برای زمینه‌ی تخت و گرادیانی خوب کار می‌کند —
(۳) متن جدید با همان رنگ و هم‌اندازه با نوشته‌ی قدیمی کشیده می‌شود.
"""
from __future__ import annotations

import copy
import io
import os
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter

from ..calendars.jalali import DayInfo, month_days
from ..export.batch import BatchResult, DayResult, _write_reports
from ..render.raster import iou, polygons_mask
from ..tgs.autodetect import _silhouette
from ..tgs.replacer import SlotReport, SlotSpec, _box, _em_polys, render_fit, render_text, slot_text
from ..validation.validator import ValidationResult
from .blobs import Blob

PNG_MAX_BYTES = 512 * 1024
SS = 4                      # ابرنمونه‌برداری برای لبه‌ی نرم


def png_filename(day: DayInfo) -> str:
    return f"{day.jy}-{day.jm:02d}-{day.jd:02d}.png"


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return mask
    im = Image.fromarray((mask * 255).astype("uint8"), "L").filter(ImageFilter.MaxFilter(2 * r + 1))
    return np.asarray(im) > 127


def fill_rect(arr: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    """مستطیل را از چهار لبه‌ی بیرونش بازسازی می‌کند (تکه‌ی کونز = درون‌یابی دوخطیِ فرا‌متناهی).
    برای زمینه‌ی تخت و گرادیانی (حتی با لبه‌ی تیز در راستای افقی/عمودی) دقیق و بدون تاری است. arr: float32 (H,W,4) پیش‌ضرب‌شده."""
    H, W = arr.shape[:2]
    x0, y0, x1, y1 = max(2, x0), max(2, y0), min(W - 2, x1), min(H - 2, y1)
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return
    L = arr[y0:y1, x0 - 2:x0].mean(axis=1)
    R = arr[y0:y1, x1:x1 + 2].mean(axis=1)
    T = arr[y0 - 2:y0, x0:x1].mean(axis=0)
    B = arr[y1:y1 + 2, x0:x1].mean(axis=0)
    c00 = arr[y0 - 2:y0, x0 - 2:x0].mean(axis=(0, 1))
    c10 = arr[y0 - 2:y0, x1:x1 + 2].mean(axis=(0, 1))
    c01 = arr[y1:y1 + 2, x0 - 2:x0].mean(axis=(0, 1))
    c11 = arr[y1:y1 + 2, x1:x1 + 2].mean(axis=(0, 1))
    u = ((np.arange(w) + 0.5) / w).astype(np.float32)[None, :, None]
    v = ((np.arange(h) + 0.5) / h).astype(np.float32)[:, None, None]
    hor = (1 - u) * L[:, None, :] + u * R[:, None, :]
    ver = (1 - v) * T[None, :, :] + v * B[None, :, :]
    bil = (1 - v) * ((1 - u) * c00 + u * c10) + v * ((1 - u) * c01 + u * c11)
    arr[y0:y1, x0:x1] = hor + ver - bil


class RasterEngine:
    def __init__(self, img: Image.Image, blobs: list[Blob], slots: list[SlotSpec], base_day: DayInfo,
                 erase_margin: int = 5):
        self.img = img.convert("RGBA")
        self.blobs = {b.id: b for b in blobs}
        self.slots = slots
        self.base_day = base_day
        self.erase_margin = erase_margin
        self._bg = None
        self.plan_errors: dict[str, str] = {}
        self.plans: dict[str, tuple] = {}
        for s in slots:
            if not s.mapped or s.candidate_id not in self.blobs:
                continue
            try:
                self.plans[s.name] = self._plan(s)
            except Exception as e:  # noqa: BLE001
                self.plan_errors[s.name] = str(e)

    # ---- کالیبراسیون: اندازه‌ی نوشته‌ی نمونه ↔ جعبه‌ی نوشته‌ی قدیمی
    def _plan(self, s: SlotSpec):
        b = self.blobs[s.candidate_id]
        x0, y0, x1, y1 = b.bbox
        lt = render_text(s, slot_text(s, self.base_day))
        bb = lt.bbox()
        if not bb:
            raise ValueError("متن نمونه گلیفی تولید نکرد: " + "; ".join(lt.warnings))
        h_em = bb[3] - bb[1]
        K = (y1 - y0) / h_em if h_em > 1e-9 else (x1 - x0) / max(bb[2] - bb[0], 1e-9)
        sample_cy = -(bb[1] + bb[3]) / 2.0          # _em_polys محور y را وارونه می‌کند
        return b, K, sample_cy

    def _background(self) -> np.ndarray:
        """زمینه‌ی تمیز (همه‌ی نوشته‌های قدیمی پاک‌شده)؛ به روز وابسته نیست، پس یک‌بار ساخته و نگه داشته می‌شود."""
        if self._bg is None:
            base = np.asarray(self.img, dtype=np.float32)
            arr = base.copy()
            arr[..., :3] *= arr[..., 3:4] / 255.0                     # پیش‌ضرب‌شده
            rects = [p[0].bbox for p in self.plans.values()]
            # تکه‌های کوچکِ جدامانده‌ی همان نوشته (نقطه‌ی حرف‌ها و …) که خوشه‌ی اصلی را همراهی می‌کنند
            mapped = {p[0].id for p in self.plans.values()}
            for sb in self.blobs.values():
                if sb.id in mapped:
                    continue
                sx0, sy0, sx1, sy1 = sb.bbox
                for i, (x0, y0, x1, y1) in enumerate(rects):
                    h, w = y1 - y0, x1 - x0
                    if ((sy1 - sy0) <= 0.5 * h and (sx1 - sx0) <= 0.5 * h
                            and x0 - 0.05 * w <= (sx0 + sx1) / 2 <= x1 + 0.05 * w
                            and y0 - 0.6 * h <= (sy0 + sy1) / 2 <= y1 + 0.6 * h):
                        rects[i] = (min(x0, sx0), min(y0, sy0), max(x1, sx1), max(y1, sy1))   # ادغام در همان مستطیل
                        break
            m = self.erase_margin
            for (x0, y0, x1, y1) in rects:
                fill_rect(arr, x0 - m, y0 - m, x1 + m, y1 + m)
            rgb = np.where(arr[..., 3:4] > 1e-3, arr[..., :3] / np.maximum(arr[..., 3:4] / 255.0, 1e-3), 0)
            self._bg = np.concatenate([np.clip(rgb, 0, 255), np.clip(arr[..., 3:4], 0, 255)], axis=-1)
        return self._bg

    def generate(self, day: DayInfo) -> tuple[Image.Image, list[SlotReport]]:
        out = self._background().copy()
        reports: list[SlotReport] = []
        for s in self.slots:
            if s.mapped and s.name not in self.plans:
                reports.append(SlotReport(s.name, slot_text(s, day), False,
                                          warnings=["کالیبراسیون ناموفق: " + self.plan_errors.get(s.name, "نامشخص")]))
        for s in self.slots:
            if s.name not in self.plans:
                continue
            pb, pK, _cy = self.plans[s.name]
            text, lt = render_fit(s, day, pK * s.scale_mul, (pb.bbox[2] - pb.bbox[0]) * s.max_width_factor * max(1.0, s.scale_mul))
            rep = SlotReport(s.name, text, False)
            try:
                rep.warnings += lt.warnings
                cov, box, scale, shrunk = self._draw(s, lt)
                if cov is None:
                    rep.warnings.append("متن خالی یا بدون گلیف")
                else:
                    self._composite(out, cov, box, self.plans[s.name][0].color)
                    rep.ok, rep.scale, rep.shrunk = True, scale, shrunk
            except Exception as e:  # noqa: BLE001
                rep.warnings.append(f"خطا: {e}")
            reports.append(rep)
        return Image.fromarray(out.astype("uint8"), "RGBA"), reports

    # ---- کشیدن یک متن روی بوم کامل (پوشش ۰..۱)
    def _draw(self, s: SlotSpec, lt):
        b, K, sample_cy = self.plans[s.name]
        polys = _em_polys(lt)
        box = _box(polys)
        if not box:
            return None, None, 0.0, False
        x0, y0, x1, y1 = b.bbox
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        K = K * s.scale_mul
        shrunk = False
        w_px = (box[2] - box[0]) * K
        limit = (x1 - x0) * s.max_width_factor * max(1.0, s.scale_mul)
        if s.fit == "shrink" and w_px > limit > 0:
            K *= limit / w_px
            shrunk = True
        tx = cx + s.dx - (box[0] + box[2]) / 2.0 * K
        ty = cy + s.dy - sample_cy * K
        pts = [[(tx + x * K, ty + y * K) for x, y in poly] for poly in polys]
        W, H = self.img.size
        pad = 3
        px0 = max(0, int(min(p[0] for poly in pts for p in poly)) - pad)
        py0 = max(0, int(min(p[1] for poly in pts for p in poly)) - pad)
        px1 = min(W, int(max(p[0] for poly in pts for p in poly)) + pad + 1)
        py1 = min(H, int(max(p[1] for poly in pts for p in poly)) + pad + 1)
        if px1 <= px0 or py1 <= py0:
            return None, None, 0.0, False
        w, h = px1 - px0, py1 - py0
        acc = np.zeros((h * SS, w * SS), dtype=bool)
        from PIL import ImageDraw
        for poly in pts:
            if len(poly) < 3:
                continue
            im = Image.new("1", (w * SS, h * SS), 0)
            ImageDraw.Draw(im).polygon([((x - px0) * SS, (y - py0) * SS) for x, y in poly], fill=1)
            acc ^= np.asarray(im, dtype=bool)
        cov = acc.reshape(h, SS, w, SS).mean(axis=(1, 3)).astype(np.float32)
        return cov, (px0, py0, px1, py1), K, shrunk

    @staticmethod
    def _composite(out: np.ndarray, cov: np.ndarray, box: tuple, color: tuple):
        px0, py0, px1, py1 = box
        reg = out[py0:py1, px0:px1]
        a = cov[..., None]
        col = np.array(color, dtype=np.float32)
        base_a = reg[..., 3:4] / 255.0
        new_a = a + base_a * (1 - a)
        rgb = np.where(new_a > 1e-4, (col * a + reg[..., :3] * base_a * (1 - a)) / np.maximum(new_a, 1e-4), reg[..., :3])
        reg[..., :3] = rgb
        reg[..., 3:4] = new_a * 255.0


# ------------------------------------------------------------------ اعتبارسنجی و خروجی
def encode_png(im: Image.Image) -> bytes:
    """PNG بهینه؛ اگر از ۵۱۲ کیلوبایت بزرگ‌تر شد، پالت‌دار (quantize) می‌شود."""
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=6)
    data = buf.getvalue()
    if len(data) > PNG_MAX_BYTES:
        q = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        buf = io.BytesIO()
        q.save(buf, "PNG", optimize=True)
        data = buf.getvalue()
    return data


def validate_png_bytes(data: bytes, reports: list[SlotReport] | None = None) -> ValidationResult:
    """قواعد مستندات تلگرام برای استیکر ثابت: PNG/WebP، یک ضلع دقیقاً ۵۱۲ و دیگری ≤۵۱۲، حداکثر ۵۱۲ کیلوبایت، زمینه‌ی شفاف."""
    res = ValidationResult(size=len(data))
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        res.add("فایل PNG معتبر", im.format == "PNG", f"فرمت: {im.format}")
    except Exception as e:  # noqa: BLE001
        res.add("فایل PNG معتبر", False, str(e))
        return res
    w, h = im.size
    res.add("ابعاد: یک ضلع دقیقاً ۵۱۲ و دیگری ≤ ۵۱۲", max(w, h) == 512 and min(w, h) <= 512, f"{w}×{h}")
    res.add("حجم ≤ ۵۱۲ کیلوبایت", len(data) <= PNG_MAX_BYTES, f"{len(data) / 1024:.0f} KB")
    rgba = im.convert("RGBA")
    a = np.asarray(rgba)[..., 3]
    res.add("دارای ناحیه‌ی شفاف (توصیه‌ی تلگرام)", (a < 255).any(), "", "warn")
    res.add("تصویر خالی نیست", bool((a > 0).any()))
    if reports is not None:
        bad = [r for r in reports if not r.ok]
        res.add("همه‌ی نوشته‌ها جایگزین شدند", not bad, "؛ ".join(f"{r.slot}: {'; '.join(r.warnings)}" for r in bad))
    return res


def generate_month_png(engine: RasterEngine, jy: int, jm: int, out_dir: str | os.PathLike, make_zip: bool = True,
                       progress: Callable[[int, int, str], None] | None = None,
                       cancel: Callable[[], bool] | None = None) -> BatchResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    days = month_days(jy, jm)
    batch = BatchResult(str(out))
    for k, day in enumerate(days):
        if cancel and cancel():
            break
        name = png_filename(day)
        dr = DayResult(day, name, False)
        try:
            im, reports = engine.generate(day)
            data = encode_png(im)
            res = validate_png_bytes(data, reports)
            dr.size, dr.precision = len(data), "png"
            for r in reports:
                dr.messages += [f"{r.slot}: {w}" for w in r.warnings]
            dr.messages += [str(c) for c in res.errors]
            for c in res.warnings:
                if c.name not in batch.notes:
                    batch.notes.append(c.name)
            if res.ok:
                (out / name).write_bytes(data)
                dr.ok = True
            else:
                rej = out / "_rejected"
                rej.mkdir(exist_ok=True)
                (rej / name).write_bytes(data)
                dr.rejected_path = str(rej / name)
        except Exception as e:  # noqa: BLE001
            dr.messages.append(f"خطا: {e}")
        batch.results.append(dr)
        if progress:
            progress(k + 1, len(days), f"{name} {'✔' if dr.ok else '✘'}")
    _write_reports(batch, jy, jm)
    if make_zip and batch.ok_count:
        zp = out / f"stickers-{jy}-{jm:02d}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
            for r in batch.results:
                if r.ok:
                    z.write(out / r.filename, r.filename)
        batch.zip_path = str(zp)
    return batch
