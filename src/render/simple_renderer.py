"""رندرر ساده‌ی نرم‌افزاری Lottie (فقط برای پیش‌نمایش و تست؛ جایگزین rlottie/تلگرام نیست).

پشتیبانی: لایه‌های شکل و precomp، parent، گروه‌ها، sh/rc/el، fill/stroke یکدست، شفافیت،
کی‌فریم‌ها. گرادیان خطی/شعاعی (fill و stroke) و رنگ‌های کی‌فریم‌دار هم پشتیبانی می‌شود.
ماسک‌ها و track matte (آلفا/لومینانس) هم پشتیبانی می‌شوند. پشتیبانی‌نشده (نادیده گرفته می‌شود): trim path، مرج‌پث، حالت‌های ترکیب (blend).
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from ..tgs.geometry import flatten_path
from ..tgs.props import (IDENTITY, Mat, mat_apply, mat_mul, opacity_at, shape_value_at, transform_matrix,
                         value_at)


def _rect_path(it: dict, frame: float) -> dict:
    sz = value_at(it.get("s"), frame)
    p = value_at(it.get("p"), frame)
    w, h = sz[0] / 2, sz[1] / 2
    x, y = p[0], p[1]
    return {"v": [[x - w, y - h], [x + w, y - h], [x + w, y + h], [x - w, y + h]],
            "i": [[0, 0]] * 4, "o": [[0, 0]] * 4, "c": True}


def _ellipse_path(it: dict, frame: float) -> dict:
    sz = value_at(it.get("s"), frame)
    p = value_at(it.get("p"), frame)
    rx, ry = sz[0] / 2, sz[1] / 2
    k = 0.5522847498
    x, y = p[0], p[1]
    return {"v": [[x, y - ry], [x + rx, y], [x, y + ry], [x - rx, y]],
            "o": [[rx * k, 0], [0, ry * k], [-rx * k, 0], [0, -ry * k]],
            "i": [[-rx * k, 0], [0, -ry * k], [rx * k, 0], [0, ry * k]], "c": True}


class Renderer:
    def __init__(self, doc: dict, size: int = 512, supersample: int = 2):
        self.doc = doc
        self.size = size
        self.ss = supersample
        self.assets = {str(a.get("id")): a for a in doc.get("assets", []) or [] if "layers" in a}

    def render(self, frame: float, bg: tuple[int, int, int, int] | None = (255, 255, 255, 255)) -> Image.Image:
        W = self.size * self.ss
        canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        k = W / float(self.doc.get("w", 512))
        base: Mat = (k, 0.0, 0.0, k, 0.0, 0.0)
        self._render_layers(canvas, self.doc.get("layers", []), frame, base, 1.0)
        img = canvas.resize((self.size, self.size), Image.LANCZOS) if self.ss > 1 else canvas
        if bg:
            back = Image.new("RGBA", img.size, bg)
            back.alpha_composite(img)
            return back
        return img

    # ---- لایه‌ها
    def _layer_matrix(self, layers, by_ind, layer, frame) -> Mat:
        m, cur, guard = IDENTITY, layer, 0
        while cur is not None and guard < 64:
            m = mat_mul(transform_matrix(cur.get("ks", {}), frame), m)
            cur = by_ind.get(cur.get("parent")) if cur.get("parent") is not None else None
            guard += 1
        return m

    @staticmethod
    def _active(layer, frame) -> bool:
        return not layer.get("hd") and layer.get("ip", -1e9) <= frame < layer.get("op", 1e9)

    def _draw_layer(self, target, layers, by_ind, layer, frame, base: Mat, opacity: float):
        m = self._layer_matrix(layers, by_ind, layer, frame)
        lop = opacity * opacity_at(layer.get("ks", {}), frame)
        full = mat_mul(base, m)
        if layer.get("ty") == 4:
            self._render_items(target, layer.get("shapes", []), frame, full, lop)
        elif layer.get("ty") == 0 and str(layer.get("refId")) in self.assets:
            sub = self.assets[str(layer["refId"])]["layers"]
            self._render_layers(target, sub, frame - layer.get("st", 0), full, lop)
        return full

    def _mask_coverage(self, layer, frame, full: Mat, size) -> np.ndarray | None:
        masks = layer.get("masksProperties") or []
        if not masks:
            return None
        W, H = size
        acc = None
        for mk in masks:
            mode = mk.get("mode", "a")
            if mode == "n":
                continue
            v = shape_value_at(mk.get("pt", {}), frame)
            cov = np.zeros((H, W), dtype=np.float32)
            if v and v.get("v"):
                poly = [mat_apply(full, x, y) for x, y in flatten_path(v, 10)]
                if len(poly) >= 3:
                    im = Image.new("L", (W, H), 0)
                    ImageDraw.Draw(im).polygon(poly, fill=255)
                    cov = np.asarray(im, dtype=np.float32) / 255.0
            op = value_at(mk.get("o"), frame)[0] / 100.0 if mk.get("o") is not None else 1.0
            if mk.get("inv"):
                cov = 1.0 - cov
            cov = cov * op
            if acc is None:
                acc = cov if mode in ("a", "i", "l", "d", "f") else np.zeros_like(cov)
                if mode == "s":
                    acc = np.ones_like(cov) * 0.0
            elif mode == "a":
                acc = np.maximum(acc, cov)
            elif mode == "s":
                acc = acc * (1.0 - cov)
            elif mode == "i":
                acc = acc * cov
        return acc

    def _render_layers(self, canvas, layers, frame, base: Mat, opacity: float):
        by_ind = {l.get("ind"): l for l in layers if "ind" in l}
        matte_of: dict[int, int] = {}
        hidden: set[int] = set()
        for i, l in enumerate(layers):
            if l.get("tt") and i > 0:
                matte_of[i] = i - 1
                hidden.add(i - 1)
        for i in reversed(range(len(layers))):
            layer = layers[i]
            if i in hidden or not self._active(layer, frame):
                continue
            needs_buf = i in matte_of or bool(layer.get("masksProperties"))
            if not needs_buf:
                self._draw_layer(canvas, layers, by_ind, layer, frame, base, opacity)
                continue
            buf = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            full = self._draw_layer(buf, layers, by_ind, layer, frame, base, opacity)
            factor = np.ones((canvas.size[1], canvas.size[0]), dtype=np.float32)
            cov = self._mask_coverage(layer, frame, mat_mul(base, self._layer_matrix(layers, by_ind, layer, frame)), canvas.size)
            if cov is not None:
                factor *= cov
            if i in matte_of:
                msrc = layers[matte_of[i]]
                mt = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                if self._active(dict(msrc, hd=False), frame):
                    self._draw_layer(mt, layers, by_ind, msrc, frame, base, opacity)
                arr = np.asarray(mt, dtype=np.float32) / 255.0
                tt = int(layer.get("tt"))
                if tt in (1, 2):
                    mf = arr[..., 3]
                else:   # لومینانس
                    mf = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]) * arr[..., 3]
                if tt in (2, 4):
                    mf = 1.0 - mf
                factor *= mf
            arr = np.asarray(buf, dtype=np.float32).copy()
            arr[..., 3] *= factor
            canvas.alpha_composite(Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGBA"))

    # ---- شکل‌ها
    def _render_items(self, canvas, items, frame, m: Mat, opacity: float):
        paths: list[tuple[int, list[list[tuple[float, float]]]]] = []
        ops = []
        for idx, it in enumerate(items):
            ty = it.get("ty")
            if it.get("hd"):
                continue
            if ty == "sh":
                v = shape_value_at(it.get("ks", {}), frame)
                if v and v.get("v"):
                    paths.append((idx, [flatten_path(v, 10)]))
            elif ty == "rc":
                paths.append((idx, [flatten_path(_rect_path(it, frame), 4)]))
            elif ty == "el":
                paths.append((idx, [flatten_path(_ellipse_path(it, frame), 12)]))
            elif ty in ("fl", "st", "gr", "gf", "gs"):
                ops.append((idx, it))
        for idx, it in sorted(ops, key=lambda t: -t[0]):
            ty = it["ty"]
            if ty == "gr":
                tr = next((x for x in it["it"] if x.get("ty") == "tr"), None)
                gm = mat_mul(m, transform_matrix(tr, frame)) if tr else m
                gop = opacity * (opacity_at(tr, frame) if tr else 1.0)
                self._render_items(canvas, it["it"], frame, gm, gop)
                continue
            polys = [mat_apply_all(m, p) for i2, pl in paths if i2 < idx for p in pl]
            if not polys:
                continue
            if ty == "fl":
                col = value_at(it.get("c"), frame)
                alpha = opacity * value_at(it.get("o"), frame)[0] / 100.0
                self._fill(canvas, polys, col, alpha, it.get("r", 1))
            elif ty == "st":
                col = value_at(it.get("c"), frame)
                alpha = opacity * value_at(it.get("o"), frame)[0] / 100.0
                w = value_at(it.get("w"), frame)[0] * (m[0] ** 2 + m[1] ** 2) ** 0.5
                self._stroke(canvas, polys, col, alpha, w)
            elif ty == "gf":
                alpha = opacity * value_at(it.get("o"), frame)[0] / 100.0
                self._fill(canvas, polys, None, alpha, it.get("r", 1), grad=(it, frame, m))
            elif ty == "gs":
                alpha = opacity * value_at(it.get("o"), frame)[0] / 100.0
                w = value_at(it.get("w"), frame)[0] * (m[0] ** 2 + m[1] ** 2) ** 0.5
                self._stroke(canvas, polys, None, alpha, w, grad=(it, frame, m))

    def _fill(self, canvas, polys, col, alpha, rule, grad=None):
        xs = [p[0] for poly in polys for p in poly]
        ys = [p[1] for poly in polys for p in poly]
        if not xs:
            return
        W = canvas.size[0]
        x0, y0 = max(int(min(xs)) - 1, 0), max(int(min(ys)) - 1, 0)
        x1, y1 = min(int(max(xs)) + 2, W), min(int(max(ys)) + 2, W)
        if x1 <= x0 or y1 <= y0:
            return
        acc = np.zeros((y1 - y0, x1 - x0), dtype=bool)
        for poly in polys:
            if len(poly) < 3:
                continue
            im = Image.new("1", (x1 - x0, y1 - y0), 0)
            ImageDraw.Draw(im).polygon([(x - x0, y - y0) for x, y in poly], fill=1)
            acc ^= np.array(im, dtype=bool)
        mask = Image.fromarray((acc * int(255 * max(0, min(1, alpha)))).astype("uint8"), "L")
        if grad is not None:
            src = _gradient_image(*grad, x0, y0, mask.size)
            a = np.asarray(src.getchannel("A"), dtype=np.float32) * np.asarray(mask, dtype=np.float32) / 255.0
            src.putalpha(Image.fromarray(a.astype("uint8"), "L"))
        else:
            rgb = tuple(int(max(0, min(1, c)) * 255) for c in col[:3])
            src = Image.new("RGBA", mask.size, rgb + (255,))
            src.putalpha(mask)
        canvas.alpha_composite(src, (x0, y0))

    def _stroke(self, canvas, polys, col, alpha, width, grad=None):
        layer = Image.new("L", canvas.size, 0)
        d = ImageDraw.Draw(layer)
        for poly in polys:
            if len(poly) >= 2:
                d.line(poly + [poly[0]], fill=int(255 * max(0, min(1, alpha))), width=max(1, int(round(width))), joint="curve")
        if grad is not None:
            src = _gradient_image(*grad, 0, 0, canvas.size)
            a = np.asarray(src.getchannel("A"), dtype=np.float32) * np.asarray(layer, dtype=np.float32) / 255.0
            src.putalpha(Image.fromarray(a.astype("uint8"), "L"))
        else:
            rgb = tuple(int(max(0, min(1, c)) * 255) for c in col[:3])
            src = Image.new("RGBA", canvas.size, rgb + (255,))
            src.putalpha(layer)
        canvas.alpha_composite(src)


def _gradient_image(it: dict, frame: float, m: Mat, x0: int, y0: int, size: tuple[int, int]) -> Image.Image:
    """تصویر RGBA گرادیان (خطی t=1 / شعاعی t=2) برای ناحیه‌ای که از (x0,y0) شروع می‌شود."""
    w, h = size
    g = it.get("g", {})
    n = int(g.get("p", 0))
    flat = value_at(g.get("k"), frame)
    flat = [float(v) for v in flat]
    # [offset, r, g, b] × n ، سپس (اختیاری) [offset, alpha] × k
    cs = np.array([flat[i * 4:(i + 1) * 4] for i in range(n)], dtype=np.float64) if n else np.zeros((0, 4))
    rest = flat[n * 4:]
    als = np.array([rest[i * 2:(i + 1) * 2] for i in range(len(rest) // 2)], dtype=np.float64)
    sx, sy = mat_apply(m, *value_at(it.get("s"), frame)[:2])
    ex, ey = mat_apply(m, *value_at(it.get("e"), frame)[:2])
    yy, xx = np.mgrid[0:h, 0:w]
    xx = xx + x0
    yy = yy + y0
    if int(it.get("t", 1)) == 2:
        r = max(((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5, 1e-6)
        t = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2) / r
    else:
        dx, dy = ex - sx, ey - sy
        L2 = max(dx * dx + dy * dy, 1e-9)
        t = ((xx - sx) * dx + (yy - sy) * dy) / L2
    t = np.clip(t, 0.0, 1.0)
    out = np.zeros((h, w, 4), dtype=np.float32)
    if len(cs):
        for ch in range(3):
            out[..., ch] = np.interp(t, cs[:, 0], cs[:, ch + 1])
    out[..., :3] = np.clip(out[..., :3], 0, 1) * 255
    out[..., 3] = (np.interp(t, als[:, 0], als[:, 1]) if len(als) else 1.0) * 255
    return Image.fromarray(out.astype("uint8"), "RGBA")


def mat_apply_all(m: Mat, pts):
    return [mat_apply(m, x, y) for x, y in pts]


def render_frame(doc: dict, frame: float, size: int = 512, supersample: int = 2, bg=(255, 255, 255, 255)) -> Image.Image:
    return Renderer(doc, size, supersample).render(frame, bg)
