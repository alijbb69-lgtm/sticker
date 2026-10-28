"""رسترسازی ساده‌ی مسیرها (برای مقایسه‌ی شکل و پیش‌نمایش)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def polygons_mask(polys: list[list[tuple[float, float]]], box: tuple[float, float, float, float],
                  size: tuple[int, int] = (96, 48), evenodd: bool = True) -> np.ndarray:
    """چندضلعی‌ها را در جعبه‌ی box (با کشیدگی غیریکنواخت) روی ماسک size رسم می‌کند."""
    w, h = size
    x0, y0, x1, y1 = box
    sx = (w - 1) / max(x1 - x0, 1e-9)
    sy = (h - 1) / max(y1 - y0, 1e-9)
    acc = np.zeros((h, w), dtype=bool)
    for poly in polys:
        if len(poly) < 3:
            continue
        im = Image.new("1", (w, h), 0)
        ImageDraw.Draw(im).polygon([((x - x0) * sx, (y - y0) * sy) for x, y in poly], fill=1)
        m = np.array(im, dtype=bool)
        acc = np.logical_xor(acc, m) if evenodd else np.logical_or(acc, m)
    return acc


def iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / float(union) if union else 0.0
