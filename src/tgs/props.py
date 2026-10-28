"""ارزیابی ویژگی‌های Lottie (ثابت یا کی‌فریم‌دار) و ماتریس‌های تبدیل دوبعدی."""
from __future__ import annotations

import math
from typing import Any

Mat = tuple[float, float, float, float, float, float]  # (a, b, c, d, e, f): x' = a x + c y + e ; y' = b x + d y + f
IDENTITY: Mat = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m: Mat, n: Mat) -> Mat:
    """m · n  (ابتدا n سپس m اعمال می‌شود)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def mat_apply(m: Mat, x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def mat_apply_vec(m: Mat, x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y, m[1] * x + m[3] * y


def mat_inv(m: Mat) -> Mat:
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("ماتریس تبدیل وارون‌پذیر نیست (مقیاس صفر)")
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(ia * e + ic * f), -(ib * e + id_ * f))


def _bez_ease(p: float, o: tuple[float, float], i: tuple[float, float]) -> float:
    """منحنی سهل‌الحرکت بزیه با نقاط کنترلی (o) و (i) در بازه‌ی [0,1]."""
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    lo, hi = 0.0, 1.0
    u = p
    for _ in range(40):
        x = 3 * (1 - u) ** 2 * u * o[0] + 3 * (1 - u) * u * u * i[0] + u ** 3
        if abs(x - p) < 1e-6:
            break
        if x < p:
            lo = u
        else:
            hi = u
        u = (lo + hi) / 2
    return 3 * (1 - u) ** 2 * u * o[1] + 3 * (1 - u) * u * u * i[1] + u ** 3


def _first(v):
    return v[0] if isinstance(v, list) else v


def _as_list(v) -> list[float]:
    return list(v) if isinstance(v, (list, tuple)) else [v]


def is_animated(prop: Any) -> bool:
    return isinstance(prop, dict) and prop.get("a") == 1


def value_at(prop: Any, frame: float) -> list[float]:
    """مقدار یک ویژگی عددی در فریم داده‌شده (همیشه به‌صورت لیست)."""
    if prop is None:
        return [0.0]
    if not isinstance(prop, dict):
        return _as_list(prop)
    k = prop.get("k")
    if prop.get("a") != 1 or not isinstance(k, list) or not k or not isinstance(k[0], dict):
        return _as_list(k)
    kfs = [kf for kf in k if "t" in kf]
    if frame <= kfs[0]["t"]:
        return _as_list(kfs[0].get("s", [0]))
    for idx, kf in enumerate(kfs):
        nxt = kfs[idx + 1] if idx + 1 < len(kfs) else None
        if nxt is None:
            if "s" in kf:
                return _as_list(kf["s"])
            prev = kfs[idx - 1] if idx > 0 else None
            return _as_list(prev.get("e", [0])) if prev else [0.0]
        if frame < nxt["t"]:
            s = _as_list(kf["s"])
            e = _as_list(kf.get("e", nxt.get("s", kf["s"])))
            if kf.get("h") == 1:
                return s
            span = nxt["t"] - kf["t"]
            p = (frame - kf["t"]) / span if span else 1.0
            o, i = kf.get("o"), kf.get("i")
            if o and i:
                p = _bez_ease(p, (_first(o["x"]), _first(o["y"])), (_first(i["x"]), _first(i["y"])))
            if kf.get("to") and kf.get("ti") and len(s) >= 2:
                to, ti = kf["to"], kf["ti"]
                u = p
                out = []
                for d in range(len(s)):
                    p0, p3 = s[d], e[d]
                    p1 = p0 + (to[d] if d < len(to) else 0)
                    p2 = p3 + (ti[d] if d < len(ti) else 0)
                    out.append((1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * p1 + 3 * (1 - u) * u * u * p2 + u ** 3 * p3)
                return out
            return [a + (b - a) * p for a, b in zip(s, e)]
    return _as_list(kfs[-1].get("s", [0]))


def transform_matrix(tr: dict, frame: float) -> Mat:
    """ماتریس یک آبجکت transform (در لایه: ks ؛ در گروه شکل: آیتم tr)."""
    a = value_at(tr.get("a"), frame) if tr.get("a") is not None else [0, 0]
    a = (a + [0, 0])[:2]
    p_prop = tr.get("p")
    if isinstance(p_prop, dict) and p_prop.get("s"):  # موقعیت جداشده
        px = value_at(p_prop.get("x"), frame)[0]
        py = value_at(p_prop.get("y"), frame)[0]
        p = [px, py]
    else:
        p = (value_at(p_prop, frame) + [0, 0])[:2] if p_prop is not None else [0, 0]
    s = value_at(tr.get("s"), frame) if tr.get("s") is not None else [100, 100]
    s = (s + [100, 100])[:2]
    r_prop = tr.get("r")
    r = value_at(r_prop, frame)[0] if r_prop is not None else 0.0
    sx, sy = s[0] / 100.0, s[1] / 100.0
    th = math.radians(r)
    cs, sn = math.cos(th), math.sin(th)
    # T(p) · R · S · T(-a)
    m_s_a: Mat = (sx, 0.0, 0.0, sy, -a[0] * sx, -a[1] * sy)
    m_r: Mat = (cs, sn, -sn, cs, 0.0, 0.0)
    m_t: Mat = (1.0, 0.0, 0.0, 1.0, p[0], p[1])
    return mat_mul(m_t, mat_mul(m_r, m_s_a))


def opacity_at(tr: dict, frame: float) -> float:
    o = tr.get("o")
    return value_at(o, frame)[0] / 100.0 if o is not None else 1.0


def shape_value(ks: dict) -> dict | None:
    """اولین مقدار مسیر (i/o/v/c) از ویژگی ks یک آیتم sh."""
    k = ks.get("k") if isinstance(ks, dict) else None
    if isinstance(k, dict):
        return k
    if isinstance(k, list) and k and isinstance(k[0], dict):
        s = k[0].get("s")
        if isinstance(s, list) and s:
            return s[0]
        if isinstance(s, dict):
            return s
    return None


def shape_value_at(ks: dict, frame: float) -> dict | None:
    """مقدار مسیر در یک فریم (بدون درون‌یابی: نزدیک‌ترین کی‌فریم قبلی)."""
    k = ks.get("k") if isinstance(ks, dict) else None
    if isinstance(k, dict):
        return k
    if isinstance(k, list) and k and isinstance(k[0], dict):
        chosen = k[0]
        for kf in k:
            if kf.get("t", 0) <= frame:
                chosen = kf
        s = chosen.get("s")
        if isinstance(s, list) and s:
            return s[0]
        if isinstance(s, dict):
            return s
    return None
