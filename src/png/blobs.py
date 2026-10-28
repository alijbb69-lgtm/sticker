"""استخراج نوشته‌ها از یک استیکر PNG (بدون OCR): پیکسل‌های «متن‌مانند» → مؤلفه‌های متصل → خوشه‌های هم‌خط.

متن نسبت به زمینه‌ی پیرامونش تیره‌تر یا روشن‌تر است؛ با تفاضل از «بسته‌شدگی/بازشدگی» مورفولوژیک (top-hat) جدا می‌شود.
خروجی با همان ساختار کاندیدهای TGS داده می‌شود تا همان موتور تشخیص خودکار (تاریخ + متغیرها) کار کند.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter

from ..tgs.analyzer import Candidate


@dataclass
class Blob:
    id: str
    bbox: tuple[int, int, int, int]            # x0, y0, x1, y1 (پیکسل، x1/y1 انحصاری)
    mask: np.ndarray                           # bool، اندازه‌ی کامل تصویر نیست؛ فقط داخل bbox
    n_components: int
    color: tuple[int, int, int] = (0, 0, 0)
    contrast: float = 255.0                    # اختلاف روشنایی متن با اطرافش؛ تزئینات هم‌رنگِ زمینه کم‌کنتراست‌اند

    @property
    def size(self):
        return self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1]


def flatten_on_white(img: Image.Image) -> np.ndarray:
    """RGBA → خاکستری با زمینه‌ی سفید برای نواحی شفاف (متن روی زمینه‌ی شفاف هم دیده شود)."""
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    bg.alpha_composite(rgba)
    return np.asarray(bg.convert("L"), dtype=np.int16)


def _morph(arr: np.ndarray, size: int, op: str) -> np.ndarray:
    im = Image.fromarray(arr.astype("uint8"), "L")
    f1, f2 = (ImageFilter.MaxFilter, ImageFilter.MinFilter) if op == "close" else (ImageFilter.MinFilter, ImageFilter.MaxFilter)
    return np.asarray(im.filter(f1(size)).filter(f2(size)), dtype=np.int16)


def _open3(m: np.ndarray) -> np.ndarray:
    # خطوط خیلی نازک (لبه‌ی شکل‌ها، سایه‌ها) حذف شوند تا به نوشته نچسبند: بازشدگی ۳×۳
    im = Image.fromarray((m * 255).astype("uint8"), "L").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return np.asarray(im) > 127


def text_masks(img: Image.Image, kernel: int = 21, thr: int = 38) -> tuple[np.ndarray, np.ndarray]:
    """(ماسک نوشته‌ی تیره، ماسک نوشته‌ی روشن) نسبت به زمینه‌ی محلی؛ پیکسل‌های تقریباً شفاف کنار گذاشته می‌شوند."""
    g = flatten_on_white(img)
    dark = _morph(g, kernel, "close") - g           # تیره‌تر از زمینه (متن تیره)
    light = g - _morph(g, kernel, "open")           # روشن‌تر از زمینه (متن روشن)
    a = np.asarray(img.convert("RGBA"))[..., 3] > 40
    return (dark > thr) & a, (light > thr) & a


def text_pixels(img: Image.Image, kernel: int = 21, thr: int = 38) -> np.ndarray:
    d, l = text_masks(img, kernel, thr)
    return _open3(d | l)


def label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """برچسب‌گذاری مؤلفه‌های متصل (۸‌همسایگی) بدون scipy."""
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    n = 0
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if lab[y0, x0]:
            continue
        n += 1
        lab[y0, x0] = n
        stack = [(y0, x0)]
        while stack:
            y, x = stack.pop()
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w and mask[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = n
                        stack.append((yy, xx))
    return lab, n


def _components(mask: np.ndarray, min_area: int = 14):
    lab, n = label(mask)
    comps = []
    if n == 0:
        return lab, comps
    ys, xs = np.nonzero(lab)
    ids = lab[ys, xs]
    order = np.argsort(ids, kind="stable")
    ys, xs, ids = ys[order], xs[order], ids[order]
    bounds = np.searchsorted(ids, np.arange(1, n + 2))
    for k in range(n):
        a, b = bounds[k], bounds[k + 1]
        if b - a < min_area:
            continue
        cy, cx = ys[a:b], xs[a:b]
        comps.append({"id": k + 1, "bbox": (int(cx.min()), int(cy.min()), int(cx.max()) + 1, int(cy.max()) + 1),
                      "area": int(b - a)})
    return lab, comps


def _merge(comps: list[dict]) -> list[list[dict]]:
    """هم‌خط و نزدیک → یک خوشه (یک «کلمه/عدد»)."""
    groups = [[c] for c in comps]

    def bb(g):
        return (min(c["bbox"][0] for c in g), min(c["bbox"][1] for c in g),
                max(c["bbox"][2] for c in g), max(c["bbox"][3] for c in g))

    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a, b = bb(groups[i]), bb(groups[j])
                ha, hb = a[3] - a[1], b[3] - b[1]
                hmax = max(ha, hb)
                ov = min(a[3], b[3]) - max(a[1], b[1])
                if ov < 0.35 * min(ha, hb):
                    continue
                gap = max(a[0], b[0]) - min(a[2], b[2])
                if gap <= 0.55 * hmax and 0.3 <= ha / max(hb, 1) <= 3.3:
                    groups[i] += groups[j]
                    del groups[j]
                    changed = True
                    break
            if changed:
                break
    return groups


def find_blobs(img: Image.Image, min_h: int = 8, max_frac: float = 0.45) -> tuple[list[Blob], np.ndarray]:
    """خوشه‌های متنی تصویر. همچنین ماسک پیکسل‌های متن را برمی‌گرداند."""
    dark_raw, light_raw = text_masks(img)
    m = _open3(dark_raw | light_raw)
    dark_m, light_m = _open3(dark_raw), _open3(light_raw)
    lab, comps = _components(m)
    W, H = img.size
    comps = [c for c in comps if (c["bbox"][3] - c["bbox"][1]) >= 3]
    blobs: list[Blob] = []
    rgba = np.asarray(img.convert("RGBA"))
    gray = flatten_on_white(img).astype(np.float32)
    for k, g in enumerate(_merge(comps)):
        x0 = min(c["bbox"][0] for c in g); y0 = min(c["bbox"][1] for c in g)
        x1 = max(c["bbox"][2] for c in g); y1 = max(c["bbox"][3] for c in g)
        w, h = x1 - x0, y1 - y0
        if h < min_h or w < 6 or w > max_frac * W * 1.9 or h > max_frac * H:
            continue
        # قطبیت: شکافِ روشنِ بین حروف هم «روشن‌تر از اطراف» حساب می‌شود؛ شکل واقعی حروف همان قطبیتی است که
        # رنگش از زمینه‌ی اطراف بیشتر فاصله دارد (شکاف‌ها هم‌رنگ زمینه‌اند)
        ring = gray[max(0, y0 - 5):y1 + 5, max(0, x0 - 5):x1 + 5].copy()
        oy, ox = y0 - max(0, y0 - 5), x0 - max(0, x0 - 5)
        ring[oy:oy + h, ox:ox + w] = np.nan
        bgl = float(np.nanmedian(ring)) if np.isfinite(ring).any() else 255.0
        cd, cl = dark_m[y0:y1, x0:x1], light_m[y0:y1, x0:x1]
        area = float(w * h)
        gcrop = gray[y0:y1, x0:x1]
        opts = [(abs(float(np.median(gcrop[x])) - bgl), x) for x in (cd, cl) if x.sum() > 0.04 * area]
        sub = max(opts, key=lambda t: t[0])[1] if opts else np.isin(lab[y0:y1, x0:x1], [c["id"] for c in g])
        # رنگ متن: میانه‌ی رنگ پیکسل‌های مرکزی خوشه
        px = rgba[y0:y1, x0:x1][sub][:, :3]
        col = tuple(int(v) for v in np.median(px, axis=0)) if len(px) else (0, 0, 0)
        inkl = float(np.median(gray[y0:y1, x0:x1][sub])) if sub.any() else 0.0
        blobs.append(Blob(f"png/{k}", (x0, y0, x1, y1), sub, len(g), col, abs(bgl - inkl)))
    return blobs, m


def text_lines(mask: np.ndarray) -> int:
    """تعداد خطوط متن در یک ناحیه (با نیم‌رخ سطری). نقطه‌ی حرف‌ها (باند کوچک) حساب نمی‌شود."""
    rows = mask.any(axis=1)
    bands, start = [], None
    gap = 0
    for i, r in enumerate(rows.tolist() + [False] * 4):
        if r:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= 3:
                bands.append((start, i - gap + 1))
                start, gap = None, 0
    if not bands:
        return 1
    big = max(b - a for a, b in bands)
    return sum(1 for a, b in bands if (b - a) >= 0.45 * big)


MIN_CONTRAST = 0       # فیلتر کنتراست خاموش است: متن کم‌رنگ (مثل OCT خاکستری روشن) هم متن است


def to_candidates(blobs: list[Blob]) -> tuple[list[Candidate], dict]:
    """کاندیدهای هم‌ساختار با TGS + داده‌ی ماسک (برای تشخیص خودکار)."""
    cands, pre = [], {}
    for b in blobs:
        plausible = text_lines(b.mask) <= 1 and b.contrast >= MIN_CONTRAST     # تک‌خطی؛ بلوکِ چندخطی (تلفن/شبکه‌ها) حذف
        if not plausible:
            cands.append(Candidate(b.id, "group", "png", 0, "", [], [int(b.id.split("/")[1])], n_paths=-1,
                                   world_bbox=tuple(float(v) for v in b.bbox)))
            continue
        x0, y0, x1, y1 = b.bbox
        c = Candidate(b.id, "group", "png", 0, "", [], [int(b.id.split("/")[1])], n_paths=-1,
                      world_bbox=(float(x0), float(y0), float(x1), float(y1)))
        im = Image.fromarray((b.mask * 255).astype("uint8"), "L").resize((96, 48), Image.BOX)
        mask = np.asarray(im) > 90
        cols = b.mask.any(axis=0)
        c.runs = int(((cols[1:]) & (~cols[:-1])).sum() + (1 if cols[0] else 0))
        cands.append(c)
        pre[b.id] = (None, (float(x0), float(y0), float(x1), float(y1)), mask, (x1 - x0) / max(y1 - y0, 1), c)
    return cands, pre
