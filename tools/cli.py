"""خط فرمان بدون رابط گرافیکی:

  python tools/cli.py قالب.tgs --year 1405 --month 8 --out خروجی [--fa-font مسیر.ttf] [--en-font مسیر.ttf]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calendars.jalali import day_info  # noqa: E402
from src.export.batch import generate_month  # noqa: E402
from src.tgs.analyzer import analyze  # noqa: E402
from src.tgs.lottie_io import load_tgs  # noqa: E402
from src.tgs.autodetect import detect  # noqa: E402
from src.tgs.replacer import SlotSpec, TemplateEngine, default_slots  # noqa: E402
from src.vector_text.fonts import default_font_path  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("template")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fa-font", default=default_font_path(True))
    ap.add_argument("--en-font", default=default_font_path(True))
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--written", help="فقط PNG: تاریخ نوشته‌شده روی استیکر به شکل سال-ماه-روز شمسی، مثل 1405-08-01")
    ap.add_argument("--assign", action="append", default=[],
                    help="فقط PNG: نگاشت دستی «نام متغیر=شماره‌ی ناحیه[:persian]»؛ بدون آن پیشنهاد خودکار می‌آید")
    a = ap.parse_args(argv)

    if a.template.lower().endswith((".png", ".webp")):
        return _png(a)
    doc = load_tgs(a.template)
    slots = default_slots(default_font_path(True), default_font_path(True))
    det = detect(doc, analyze(doc), slots)
    print(det.message)
    if not det.ok:
        return 2
    base = det.base_day
    for s in slots:
        s.fa_font, s.en_font = a.fa_font, a.en_font
    for s in slots:
        print(("✔" if s.mapped else "✘"), s.name, f"{s.confidence:.0%}" if s.mapped else "نگاشت نشد")
    eng = TemplateEngine(doc, slots, base)
    res = generate_month(eng, a.year, a.month, a.out, not a.no_zip,
                         progress=lambda i, n, m: print(f"[{i}/{n}] {m}"))
    print(f"\n{res.ok_count}/{len(res.results)} فایل معتبر")
    for r in res.failed:
        print("FAIL", r.filename, r.messages)
    return 0 if not res.failed else 1


def _png(a) -> int:
    from PIL import Image
    from src.calendars.jalali import day_info
    from src.png.blobs import find_blobs, to_candidates
    from src.png.engine import RasterEngine, generate_month_png
    from src.png.setup import apply_assignment, suggest
    from src.tgs.autodetect import detect
    im = Image.open(a.template).convert("RGBA")
    blobs, _ = find_blobs(im)
    cands, pre = to_candidates(blobs)
    slots = default_slots(a.fa_font, a.en_font)
    if a.written:
        base = day_info(*[int(x) for x in a.written.split("-")])
    else:
        det = detect(None, cands, slots, prebuilt=pre)
        print(det.message)
        if not det.ok:
            return 2
        base = det.base_day
        a.assign = a.assign or [f"{s.name}={s.candidate_id.split('/')[1]}:{s.digits}" for s in slots if s.mapped]
    if a.assign:
        asg = {}
        for item in a.assign:
            name, _, v = item.partition("=")
            num, _, dg = v.partition(":")
            asg[name] = (f"png/{num}", dg or "keep")
    else:
        asg = suggest(slots, pre, base)
    apply_assignment(slots, asg, cands)
    for b in blobs:
        print("ناحیه", b.id.split("/")[1], b.bbox)
    for s in slots:
        print(("✔" if s.mapped else "✘"), s.name, s.candidate_id or "")
    res = generate_month_png(RasterEngine(im, blobs, slots, base), a.year, a.month, a.out, not a.no_zip,
                             progress=lambda i, n, m: print(f"[{i}/{n}] {m}"))
    print(f"\n{res.ok_count}/{len(res.results)} فایل معتبر")
    return 0 if not res.failed else 1


if __name__ == "__main__":
    sys.exit(main())
