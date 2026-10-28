"""استیکر ثابت (PNG): ناحیه‌یابی، پاک‌کردن/بازنویسی، اعتبارسنجی طبق مستندات تلگرام، تولید ماهانه."""
import io
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from src.calendars.jalali import day_info
from src.png.blobs import find_blobs, to_candidates
from src.png.engine import RasterEngine, encode_png, generate_month_png, validate_png_bytes
from src.png.session import file_hash, load_session, stale_slots
from src.png.setup import apply_assignment, suggest
from src.tgs.autodetect import detect
from src.tgs.replacer import fit_kashida, stretch_text
from src.tgs.replacer import default_slots
from src.vector_text.fonts import default_font_path

PATH = os.path.join(os.path.dirname(__file__), "data", "gold_static.png")
ASSIGN = {"روز شمسی": ("png/4", "persian"), "روز میلادی": ("png/11", "keep"), "روز هفته (فارسی)": ("png/1", "keep"),
          "سال شمسی": ("png/6", "persian"), "ماه شمسی": ("png/5", "keep"), "سال میلادی": ("png/13", "keep"),
          "ماه میلادی": ("png/12", "keep")}


class PngTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp = default_font_path(True)
        cls.im = Image.open(PATH).convert("RGBA")
        cls.blobs, _ = find_blobs(cls.im)
        cls.cands, cls.pre = to_candidates(cls.blobs)
        cls.base = day_info(1405, 8, 1)          # جمعه ۱ آبان ۱۴۰۵ = 23 Oct 2026
        cls.slots = default_slots(cls.fp, cls.fp)
        apply_assignment(cls.slots, ASSIGN, cls.cands)
        cls.eng = RasterEngine(cls.im, cls.blobs, cls.slots, cls.base)

    def test_blobs_found(self):
        ids = {b.id: b.bbox for b in self.blobs}
        for k in ("png/1", "png/4", "png/5", "png/6", "png/11", "png/12", "png/13"):
            self.assertIn(k, ids)

    def test_auto_detect_date_and_slots(self):
        sl = default_slots(self.fp, self.fp)
        det = detect(None, self.cands, sl, years=range(1400, 1411), prebuilt=self.pre)
        self.assertTrue(det.ok, det.message)
        d = det.base_day
        self.assertEqual((d.jy, d.jm, d.jd), (1405, 8, 1))          # جمعه ۲۳ اکتبر ۲۰۲۶
        got = {s.name: s.candidate_id for s in sl if s.mapped}
        for name, (bid, _dg) in ASSIGN.items():
            self.assertEqual(got.get(name), bid, name)
        self.assertNotIn("روز هفته (انگلیسی)", got)                  # این استیکر روز هفته‌ی انگلیسی ندارد

    def test_suggest_with_known_date(self):
        sg = suggest(default_slots(self.fp, self.fp), self.pre, self.base)
        for name, (bid, _dg) in ASSIGN.items():
            self.assertEqual(sg.get(name, (None,))[0], bid, name)

    def test_stretch_patterns(self):
        self.assertEqual(stretch_text("شنبه", 3), "شـــنـــبـــه")
        self.assertEqual(stretch_text("دوشنبه", 1), "دوشـنـبـه")
        self.assertEqual(stretch_text("چهارشنبه", 1), "چهارشـنـبـه")
        self.assertEqual(stretch_text("جمعه", 0), "جمعه")
        self.assertIn("\u0640", stretch_text("یک‌شنبه", 2))

    def test_kashida_kept_for_all_days(self):
        sl = default_slots(self.fp, self.fp)
        apply_assignment(sl, ASSIGN, self.cands)
        asp = {s.name: (b.bbox[2] - b.bbox[0]) / (b.bbox[3] - b.bbox[1]) for s in sl if s.mapped
               for b in self.blobs if b.id == s.candidate_id}
        found = fit_kashida(sl, self.base, asp)
        self.assertGreaterEqual(found.get("روز هفته (فارسی)", 0), 1)       # «جـمـعـه» در قالب کشیده است
        eng = RasterEngine(self.im, self.blobs, sl, self.base)
        seen = set()
        for d in range(1, 8):
            _, reps = eng.generate(day_info(1405, 8, d))
            wd = next(r for r in reps if r.slot == "روز هفته (فارسی)")
            self.assertTrue(wd.ok)
            self.assertIn("\u0640", wd.text)
            seen.add(wd.text)
        self.assertEqual(len(seen), 7)

    def test_session_auto_and_ignores_stale_saved_assignment(self):
        wrong = {"روز شمسی": ["png/9", "keep"], "روز میلادی": ["png/9", "keep"], "روز هفته (فارسی)": ["png/16", "keep"]}
        h = file_hash(PATH)
        # تنظیمات قدیمیِ خودکار (manual نیست) یا مال فایل دیگر نباید نگاشت درست را خراب کنند
        for saved in ({"hash": h, "manual": False, "assign": wrong, "base": [1405, 8, 1]},
                      {"hash": "x", "manual": True, "assign": wrong, "base": [1405, 8, 1]}):
            ss = load_session(PATH, self.fp, self.fp, saved)
            self.assertEqual((ss.base_day.jy, ss.base_day.jm, ss.base_day.jd), (1405, 8, 1))
            self.assertEqual({k: v[0] for k, v in ss.assign.items()}, {k: v[0] for k, v in ASSIGN.items()})
        # اصلاح دستیِ همین فایل حفظ می‌شود
        ok = load_session(PATH, self.fp, self.fp, {"hash": h, "manual": True, "assign": wrong, "base": [1405, 8, 1]})
        self.assertFalse(ok.auto)

    def test_everything_changes_with_the_date(self):
        ss = load_session(PATH, self.fp, self.fp)
        eng = RasterEngine(ss.img, ss.blobs, ss.slots, ss.base_day)
        self.assertEqual(stale_slots(eng, day_info(1405, 8, 1), day_info(1405, 9, 2)), [])
        a, _ = eng.generate(day_info(1405, 9, 1))      # ۱ آذر ۱۴۰۵ = یک‌شنبه ۲۲ نوامبر
        b, rep = eng.generate(day_info(1405, 9, 2))
        t = {r.slot: r.text for r in rep}
        self.assertEqual(t["روز شمسی"], "02")
        self.assertEqual(t["روز میلادی"], "23")
        self.assertIn("\u0640", t["روز هفته (فارسی)"])
        self.assertTrue(np.any(np.asarray(a) != np.asarray(b)))

    def test_roundtrip_detect_on_generated_stickers(self):
        # استیکرِ ساخته‌شده (با روز هفته‌ی کشیده و ناپیوسته) دوباره باید درست خوانده شود
        import tempfile
        eng = RasterEngine(self.im, self.blobs, load_session(PATH, self.fp, self.fp).slots, self.base)
        for ymd in [(1405, 5, 9), (1405, 2, 17), (1405, 12, 15)]:
            out, _ = eng.generate(day_info(*ymd))
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "t.png")
                out.save(f)
                ss = load_session(f, self.fp, self.fp)
            self.assertEqual((ss.base_day.jy, ss.base_day.jm, ss.base_day.jd), ymd)
            self.assertTrue(ss.assign.get("روز شمسی") and ss.assign.get("روز میلادی"))

    def test_background_clean_and_fast(self):
        import time
        self.eng.generate(day_info(1405, 8, 2))
        t = time.time()
        out, _ = self.eng.generate(day_info(1405, 8, 3))
        self.assertLess(time.time() - t, 0.5)
        # جای نوشته‌ی قدیمی (مثل «OCT») باید زمینه‌ی تمیز باشد، نه رد نوشته‌ی قبلی
        a = np.asarray(self.eng._background())[283:308, 386:458, :3].astype(float)
        self.assertLess(a.std(axis=(0, 1)).max(), 12)

    def test_generate_replaces_all_and_validates(self):
        out, reps = self.eng.generate(day_info(1405, 8, 10))
        self.assertTrue(all(r.ok for r in reps), [(r.slot, r.warnings) for r in reps])
        texts = {r.slot: r.text for r in reps}
        self.assertEqual(texts["روز میلادی"], "01")
        self.assertEqual(texts["ماه میلادی"], "NOV")
        self.assertEqual(out.size, (512, 512))
        data = encode_png(out)
        res = validate_png_bytes(data, reps)
        self.assertTrue(res.ok, [str(c) for c in res.errors])
        self.assertLessEqual(len(data), 512 * 1024)

    def test_untouched_regions_identical(self):
        out, _ = self.eng.generate(day_info(1405, 8, 10))
        a, b = np.asarray(self.im), np.asarray(out)
        logo = (slice(0, 110), slice(340, 512))           # لوگو بالا-راست
        phone = (slice(400, 485), slice(60, 480))          # خط تلفن/شبکه‌ها
        for reg in (logo, phone):
            x, y = a[reg].astype(int), b[reg].astype(int)
            vis = x[..., 3] > 0
            self.assertLessEqual(np.abs(x[..., 3] - y[..., 3]).max(), 1)
            self.assertLessEqual(np.abs(x[..., :3] - y[..., :3])[vis].max(), 3)   # گرد‌کردنِ پیش‌ضرب

    def test_validator_negative(self):
        def enc(size, fmt="PNG"):
            buf = io.BytesIO()
            Image.new("RGBA", size, (255, 0, 0, 255)).save(buf, fmt)
            return buf.getvalue()
        self.assertFalse(validate_png_bytes(enc((300, 300))).ok)        # هیچ ضلعی ۵۱۲ نیست
        self.assertFalse(validate_png_bytes(enc((600, 512))).ok)        # یک ضلع بزرگ‌تر از ۵۱۲
        self.assertFalse(validate_png_bytes(b"not a png").ok)
        self.assertTrue(validate_png_bytes(enc((512, 200))).ok)

    def test_month(self):
        with tempfile.TemporaryDirectory() as d:
            res = generate_month_png(self.eng, 1405, 8, d, True)
            self.assertEqual(len(res.results), 30)
            self.assertEqual(res.ok_count, 30, [(r.filename, r.messages) for r in res.failed])
            self.assertTrue(os.path.exists(os.path.join(d, "1405-08-30.png")))
            self.assertTrue(res.zip_path and os.path.exists(res.zip_path))


if __name__ == "__main__":
    unittest.main()
