"""آزمون روی قالب واقعیِ صرافی (۰۹ اسفند ۱۴۰۴ = شنبه ۲۸ فوریه ۲۰۲۶)."""
import os
import tempfile
import unittest

import numpy as np

from src.calendars.jalali import day_info, month_days
from src.export.batch import generate_month
from src.render.simple_renderer import render_frame
from src.tgs.analyzer import analyze
from src.tgs.lottie_io import dump_tgs_bytes, load_tgs
from src.tgs.replacer import TemplateEngine, auto_map, default_slots
from src.validation.validator import validate_bytes
from src.vector_text.fonts import default_font_path

PATH = os.path.join(os.path.dirname(__file__), "data", "oxin_template.tgs")

# لایه‌ی هر متغیر در قالب (نام لایه‌ها گمراه‌کننده‌اند؛ شناسایی باید از روی شکل باشد)
EXPECTED = {"روز شمسی": 0, "روز میلادی": 1, "روز هفته (انگلیسی)": 2, "روز هفته (فارسی)": 3,
            "سال شمسی": 4, "ماه شمسی": 5, "سال میلادی": 6, "ماه میلادی": 7}


class RealTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp = default_font_path(True)
        cls.doc = load_tgs(PATH)
        cls.base = day_info(1404, 12, 9)
        cls.slots = default_slots(cls.fp, cls.fp)
        auto_map(cls.doc, analyze(cls.doc), cls.slots, cls.base)
        cls.engine = TemplateEngine(cls.doc, cls.slots, cls.base)

    def test_base_date(self):
        self.assertEqual(self.base.date.isoformat(), "2026-02-28")
        self.assertEqual(self.base.weekday_en, "SATURDAY")

    def test_auto_mapping_matches_layers(self):
        got = {s.name: s.layer_pos for s in self.slots if s.mapped}
        self.assertEqual(got, EXPECTED)

    def test_persian_digits_detected_for_jalali(self):
        by = {s.name: s for s in self.slots}
        self.assertEqual(by["روز شمسی"].digits, "persian")
        self.assertEqual(by["سال شمسی"].digits, "persian")
        self.assertEqual(by["سال میلادی"].digits, "keep")

    def test_base_day_reproduces_original_look(self):
        # فونت همراه (DejaVu) با فونت قالب فرق دارد، پس تفاوت صفر نیست؛ ولی باید کم باشد
        # و برای «همان تاریخ» به‌طور معنی‌داری کمتر از «تاریخ دیگر» باشد (یعنی متن‌ها سر جای درست نشسته‌اند).
        def diff(doc, f):
            a = np.asarray(render_frame(self.doc, f, 256, 1, bg=(0, 0, 0, 255)).convert("L"), dtype=float)
            b = np.asarray(render_frame(doc, f, 256, 1, bg=(0, 0, 0, 255)).convert("L"), dtype=float)
            return np.abs(a - b).mean()
        same, _ = self.engine.generate(self.base)
        other, _ = self.engine.generate(day_info(1404, 12, 20))
        for f in (0, 10, 19):
            ds, do = diff(same, f), diff(other, f)
            self.assertLess(ds, 3.0, f"frame {f}: {ds:.2f}")
            self.assertLess(ds, 0.85 * do, f"frame {f}: same={ds:.2f} other={do:.2f}")

    def test_branding_layers_untouched(self):
        doc, _ = self.engine.generate(day_info(1404, 12, 20))
        mapped = set(EXPECTED.values())
        for i, (a, b) in enumerate(zip(self.doc["layers"], doc["layers"])):
            if i not in mapped:
                self.assertEqual(a, b, a.get("nm"))
        for i in mapped:   # ترنسفورم/انیمیشن لایه‌های متنی همان است
            self.assertEqual(self.doc["layers"][i]["ks"], doc["layers"][i]["ks"])

    def test_whole_month_valid(self):
        with tempfile.TemporaryDirectory() as d:
            b = generate_month(self.engine, 1404, 12, d)
            self.assertEqual(b.ok_count, 29, [(r.filename, r.messages) for r in b.failed])
            self.assertTrue(all(r.size <= 64 * 1024 for r in b.results))

    def test_all_weekdays_and_months_in_year(self):
        # هر ۱۲ ماه: روز اول و آخر معتبر
        for jm in range(1, 13):
            days = month_days(1404, jm)
            for day in (days[0], days[-1]):
                doc, reps = self.engine.generate(day)
                res = validate_bytes(dump_tgs_bytes(doc), reps)
                self.assertTrue(res.ok, (day, [str(c) for c in res.errors]))


if __name__ == "__main__":
    unittest.main()


class WrongTemplateTests(unittest.TestCase):
    """قالب بدون نوشته‌ی تاریخ (فایل اول کاربر) نباید به‌عنوان قالب معتبر پذیرفته شود."""

    def test_blank_template_rejected_and_real_accepted(self):
        from src.tgs.replacer import weak_slots
        fp = default_font_path(True)
        blank = load_tgs(os.path.join(os.path.dirname(__file__), "data", "blank_no_dates.tgs"))
        s1 = default_slots(fp, fp)
        auto_map(blank, analyze(blank), s1, day_info(1404, 12, 9))
        self.assertTrue(weak_slots(s1))
        real = load_tgs(PATH)
        s2 = default_slots(fp, fp)
        auto_map(real, analyze(real), s2, day_info(1404, 12, 9))
        self.assertEqual(weak_slots(s2), [])


class AutoDetectTests(unittest.TestCase):
    """تشخیص کاملاً خودکار (بدون ورودی کاربر)."""

    def _detect(self, path):
        from src.tgs.autodetect import detect
        fp = default_font_path(True)
        doc = load_tgs(path)
        slots = default_slots(fp, fp)
        return detect(doc, analyze(doc), slots), slots

    def test_detects_date_and_layers_on_real_template(self):
        det, slots = self._detect(PATH)
        self.assertTrue(det.ok, det.message)
        self.assertEqual((det.base_day.jy, det.base_day.jm, det.base_day.jd), (1404, 12, 9))
        self.assertEqual({s.name: s.layer_pos for s in slots if s.mapped}, EXPECTED)

    def test_blank_template_is_rejected(self):
        # قالب خالی (دو کادر بدون تاریخ + برند): نباید چیزی نگاشت شود و نباید تلفن/برند خراب شود
        det, slots = self._detect(os.path.join(os.path.dirname(__file__), "data", "oxin_blank_template.tgs"))
        self.assertFalse(det.ok)
        self.assertFalse(any(s.mapped for s in slots))

    def test_sample_template_detected(self):
        from src.tgs.sample_template import build_sample_template
        from src.tgs.autodetect import detect
        fp = default_font_path(True)
        doc = build_sample_template(fp)
        slots = default_slots(fp, fp)
        det = detect(doc, analyze(doc), slots)
        self.assertTrue(det.ok, det.message)
        self.assertEqual((det.base_day.jy, det.base_day.jm, det.base_day.jd), (1405, 8, 2))


class FontFailureTests(unittest.TestCase):
    def test_unusable_font_is_reported_not_skipped(self):
        # اگر فونتِ یک متغیر قابل استفاده نباشد، نتیجه باید «ناموفق» باشد نه اینکه متن قدیمی بماند
        fp = default_font_path(True)
        doc = load_tgs(PATH)
        slots = default_slots(fp, fp)
        auto_map(doc, analyze(doc), slots, day_info(1404, 12, 9))
        for s in slots:
            if s.name == "ماه میلادی":
                s.fa_font = s.en_font = "/nonexistent/font.ttf"
        eng = TemplateEngine(doc, slots, day_info(1404, 12, 9))
        out, reps = eng.generate(day_info(1405, 10, 1))
        bad = [r for r in reps if not r.ok]
        self.assertEqual([r.slot for r in bad], ["ماه میلادی"])
        res = validate_bytes(dump_tgs_bytes(out), reps)
        self.assertFalse(res.ok)

    def test_separate_fonts_applied(self):
        fp = default_font_path(True)
        doc = load_tgs(PATH)
        slots = default_slots(fp, fp)
        auto_map(doc, analyze(doc), slots, day_info(1404, 12, 9))
        eng = TemplateEngine(doc, slots, day_info(1404, 12, 9))
        out, reps = eng.generate(day_info(1405, 10, 1))
        texts = {r.slot: r.text for r in reps}
        self.assertEqual(texts["ماه میلادی"], "DEC")
        self.assertEqual(texts["روز میلادی"], "22")
        self.assertEqual(texts["سال میلادی"], "2026")
        self.assertEqual(texts["ماه شمسی"], "دی")


GOLD = os.path.join(os.path.dirname(__file__), "data", "gold_shadow_template.tgs")


class TwinLayerTests(unittest.TestCase):
    """قالب طلایی: هر متن چند بار (سایه/کانتور/گرادیان) تکرار شده؛ همه‌ی کپی‌ها باید عوض شوند."""

    def test_all_copies_replaced(self):
        from src.tgs.autodetect import detect
        fp = default_font_path(True)
        doc = load_tgs(GOLD)
        slots = default_slots(fp, fp)
        det = detect(doc, analyze(doc), slots)
        self.assertTrue(det.ok, det.message)
        self.assertEqual(len([s for s in slots if "کپی" not in s.name]), 8)
        self.assertGreater(len(slots), 8)
        eng = TemplateEngine(doc, slots, det.base_day)
        out, reps = eng.generate(day_info(1405, 8, 10))
        self.assertTrue(all(r.ok for r in reps), [r for r in reps if not r.ok])
        base = {r.slot: r.text for r in reps if "کپی" not in r.slot}
        for r in reps:
            if "کپی" in r.slot:
                self.assertEqual(r.text, base[r.slot.rsplit(" (کپی", 1)[0]], r.slot)
        self.assertEqual(base["ماه میلادی"], "NOV")
        self.assertEqual(base["روز میلادی"], "01")
        res = validate_bytes(dump_tgs_bytes(out), reps)
        self.assertTrue(res.ok, [c for c in res.checks if not c.ok])


class CalendarEdgeTests(unittest.TestCase):
    def test_aban_10_1405_is_nov_1(self):
        d = day_info(1405, 8, 10)
        self.assertEqual((d.date.year, d.date.month, d.date.day), (2026, 11, 1))

    def test_every_day_matches_python_date(self):
        import datetime as dt
        d0 = dt.date(2026, 3, 21)          # ۱ فروردین ۱۴۰۵
        n = 0
        for jm in range(1, 13):
            for d in month_days(1405, jm):
                self.assertEqual(d.date, d0 + dt.timedelta(days=n), (d.jm, d.jd))
                n += 1


class GoldRealTests(unittest.TestCase):
    """قالب طلایی واقعی: ماه فارسی با کشیده («آبـــان»)، OCT توخالی، روز هفته‌ی فقط انگلیسی، لوگو/شماره نباید دست بخورند."""
    PATH = os.path.join(os.path.dirname(__file__), "data", "gold_real.tgs")

    def test_detect_and_generate(self):
        from src.tgs.autodetect import detect_best
        fp = default_font_path(True)
        doc = load_tgs(self.PATH)
        slots, det = detect_best(doc, analyze(doc), fp, fp)
        self.assertTrue(det.ok, det.message)
        self.assertEqual((det.base_day.jy, det.base_day.jm, det.base_day.jd), (1405, 8, 2))
        mapped = {s.name: s.layer_pos for s in slots if s.mapped}
        self.assertEqual(mapped, {"روز شمسی": 0, "روز میلادی": 1, "روز هفته (انگلیسی)": 2, "سال میلادی": 3,
                                  "ماه میلادی": 4, "ماه شمسی": 11, "سال شمسی": 12})
        eng = TemplateEngine(doc, slots, det.base_day)
        out, reps = eng.generate(day_info(1405, 8, 10))
        texts = {r.slot: r.text for r in reps}
        self.assertEqual((texts["ماه میلادی"], texts["روز میلادی"], texts["روز هفته (انگلیسی)"]), ("NOV", "01", "SUNDAY"))
        self.assertTrue(all(r.ok for r in reps))
        # لوگو و شماره‌ها (لایه‌های ۵ تا ۱۰ و ۱۳) بدون تغییر
        for i in (5, 7, 8, 9, 10, 13):
            self.assertEqual(out["layers"][i], doc["layers"][i], i)


class SizeTests(unittest.TestCase):
    def test_scale_mul_changes_size_and_stays_valid(self):
        from src.tgs.autodetect import detect_best
        fp = default_font_path(True)
        doc = load_tgs(GoldRealTests.PATH)
        slots, det = detect_best(doc, analyze(doc), fp, fp)
        day = day_info(1405, 8, 10)

        def width(mul):
            for s in slots:
                if s.name == "روز میلادی":
                    s.scale_mul = mul
            out, reps = TemplateEngine(doc, slots, det.base_day).generate(day)
            self.assertTrue(all(r.ok for r in reps))
            im = render_frame(out, 45, 512, 1, bg=(0, 0, 0, 255)).convert("L")
            a = np.asarray(im.crop((60, 160, 200, 260)))
            return int((a > 190).sum())
        self.assertGreater(width(1.0), width(0.6) * 1.3)


class FontIndependenceTests(unittest.TestCase):
    """تغییر فونت فارسی نباید ظاهر نوشته‌های میلادی را تغییر دهد (و برعکس)."""

    def test_persian_font_does_not_touch_english_layers(self):
        import json
        from src.tgs.autodetect import detect_best
        from src.vector_text.fonts import list_font_files
        fp = default_font_path(True)
        alt = next(f for f in list_font_files() if "DejaVuSans.ttf" in f)
        for path in (GoldRealTests.PATH, PATH, GOLD):
            doc = load_tgs(path)
            slots, det = detect_best(doc, analyze(doc), fp, fp)
            for s in slots:
                if "میلادی" in s.name or "انگلیسی" in s.name:
                    self.assertEqual(s.digits, "keep", s.name)
            en_layers = {s.layer_pos for s in slots if s.mapped and ("میلادی" in s.name or "انگلیسی" in s.name)}

            def gen(fa):
                for s in slots:
                    s.fa_font, s.en_font = fa, fp
                out, _ = TemplateEngine(doc, slots, det.base_day).generate(day_info(1405, 8, 10))
                return {i: json.dumps(out["layers"][i]["shapes"], sort_keys=True) for i in en_layers}
            self.assertEqual(gen(fp), gen(alt), path)


class KashidaTemplateTests(unittest.TestCase):
    """قالب با «شـنـبـه» کشیده: روز هفته‌ی فارسی تشخیص داده شود، روز انگلیسی/شماره‌تلفن/لوگو خودکار اضافه نشود."""
    PATH = os.path.join(os.path.dirname(__file__), "data", "gold_kashida.tgs")

    def test_detect_and_generate(self):
        from src.tgs.autodetect import detect_best
        fp = default_font_path(True)
        doc = load_tgs(self.PATH)
        slots, det = detect_best(doc, analyze(doc), fp, fp)
        self.assertTrue(det.ok, det.message)
        mapped = {s.name: s.layer_pos for s in slots if s.mapped}
        self.assertEqual(mapped.get("روز هفته (فارسی)"), 2)
        self.assertNotIn("روز هفته (انگلیسی)", mapped)
        self.assertFalse(any(v in (7, 8, 10, 11) for v in mapped.values()), mapped)
        out, reps = TemplateEngine(doc, slots, det.base_day).generate(day_info(1405, 8, 10))
        texts = {r.slot: r.text for r in reps}
        self.assertEqual(texts["روز هفته (فارسی)"], "یک‌شنبه")
        self.assertTrue(all(r.ok for r in reps))
        for i in (7, 8, 10, 11):
            self.assertEqual(out["layers"][i], doc["layers"][i], i)
