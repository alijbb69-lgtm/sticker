"""تولید دسته‌ای استیکرهای یک ماه، اعتبارسنجی، گزارش و ZIP."""
from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..calendars.jalali import DayInfo, month_days
from ..tgs.lottie_io import TGS_MAX_BYTES, dump_tgs_bytes
from ..tgs.replacer import TemplateEngine
from ..validation.validator import ValidationResult, validate_bytes

# نردبان کاهش حجم: (دقت مسیرهای جدید، گرد کردن سراسری یا None)
SIZE_LADDER = [(2, None), (1, None), (1, 3), (1, 2)]


@dataclass
class DayResult:
    day: DayInfo
    filename: str
    ok: bool
    size: int = 0
    precision: str = ""
    messages: list[str] = field(default_factory=list)
    rejected_path: str | None = None


@dataclass
class BatchResult:
    out_dir: str
    results: list[DayResult] = field(default_factory=list)
    zip_path: str | None = None
    notes: list[str] = field(default_factory=list)   # هشدارهای غیرخطا (یک‌بار برای کل ماه)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> list[DayResult]:
        return [r for r in self.results if not r.ok]


def day_filename(day: DayInfo) -> str:
    return f"{day.jy}-{day.jm:02d}-{day.jd:02d}.tgs"


def build_day(engine: TemplateEngine, day: DayInfo) -> tuple[bytes, ValidationResult, list, str]:
    """یک روز را می‌سازد؛ در صورت زیاد بودن حجم از نردبان کاهش دقت استفاده می‌کند."""
    last = None
    for path_nd, global_nd in SIZE_LADDER:
        doc, reports = engine.generate(day, nd=path_nd)
        data = dump_tgs_bytes(doc, global_nd)
        res = validate_bytes(data, reports)
        label = f"مسیرها {path_nd} رقم اعشار" + (f"، کل فایل {global_nd} رقم" if global_nd else "")
        last = (data, res, reports, label)
        if len(data) <= TGS_MAX_BYTES:
            break
    return last  # type: ignore[return-value]


def generate_month(engine: TemplateEngine, jy: int, jm: int, out_dir: str | os.PathLike,
                   make_zip: bool = True, progress: Callable[[int, int, str], None] | None = None,
                   cancel: Callable[[], bool] | None = None) -> BatchResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    days = month_days(jy, jm)
    batch = BatchResult(str(out))
    for k, day in enumerate(days):
        if cancel and cancel():
            break
        name = day_filename(day)
        dr = DayResult(day, name, False)
        try:
            data, res, reports, label = build_day(engine, day)
            dr.size, dr.precision = len(data), label
            for r in reports:
                dr.messages += [f"{r.slot}: {w}" for w in r.warnings]
            dr.messages += [str(c) for c in res.errors]
            for c in res.warnings:
                key = c.name if "rlottie" in c.name else f"{c.name} (در قالب اصلی نیز ممکن است وجود داشته باشد)"
                if key not in batch.notes:
                    batch.notes.append(key)
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


def _write_reports(batch: BatchResult, jy: int, jm: int):
    out = Path(batch.out_dir)
    rows = [{"file": r.filename, "ok": r.ok, "size": r.size, "gregorian": r.day.date.isoformat(),
             "weekday": r.day.weekday_en, "precision": r.precision, "messages": r.messages}
            for r in batch.results]
    (out / "report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"گزارش تولید استیکرهای {jy}/{jm:02d} — موفق: {batch.ok_count} از {len(batch.results)}", ""]
    lines += [f"هشدار: {n}" for n in batch.notes] + ([""] if batch.notes else [])
    for r in batch.results:
        lines.append(f"{'OK  ' if r.ok else 'FAIL'} {r.filename}  {r.size:>6} B  {r.day.date}  {r.day.weekday_en}")
        for m in r.messages:
            lines.append(f"      - {m}")
    (out / "report.txt").write_text("\n".join(lines), encoding="utf-8")
