"""خواندن و نوشتن فایل‌های TGS (Lottie JSON + GZIP)."""
from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any

TGS_MAX_BYTES = 64 * 1024


def load_tgs_bytes(data: bytes) -> dict:
    try:
        raw = gzip.decompress(data)
    except OSError:
        raw = data  # شاید JSON خام (Lottie) باشد
    return json.loads(raw.decode("utf-8"))


def load_tgs(path: str | Path) -> dict:
    return load_tgs_bytes(Path(path).read_bytes())


def round_floats(obj: Any, nd: int) -> Any:
    """گرد کردن اعداد اعشاری برای کاهش حجم (درجا؛ مقدار جدید را برمی‌گرداند)."""
    if isinstance(obj, float):
        r = round(obj, nd)
        return int(r) if r == int(r) else r
    if isinstance(obj, list):
        return [round_floats(x, nd) for x in obj]
    if isinstance(obj, dict):
        return {k: round_floats(v, nd) for k, v in obj.items()}
    return obj


def dump_tgs_bytes(doc: dict, nd: int | None = None) -> bytes:
    d = round_floats(doc, nd) if nd is not None else doc
    raw = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def save_tgs(doc: dict, path: str | Path, nd: int | None = None) -> int:
    data = dump_tgs_bytes(doc, nd)
    Path(path).write_bytes(data)
    return len(data)


def clone(doc: dict) -> dict:
    return copy.deepcopy(doc)
