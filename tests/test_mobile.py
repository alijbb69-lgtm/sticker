"""هسته‌ی نسخه‌ی موبایل (بدون Kivy): بارگذاری، پیش‌نمایش، تولید ماهانه و نمایش فارسی."""
import os
import tempfile
import unittest

from src.mobile.core import Project
from src.mobile.rtl import visual

D = os.path.join(os.path.dirname(__file__), "data")


class MobileCoreTests(unittest.TestCase):
    def test_png_flow(self):
        p = Project()
        self.assertTrue(p.load(os.path.join(D, "gold_static.png")).startswith("✔"))
        im, info = p.preview(1405, 9, 1)
        self.assertEqual(im.size, (512, 512))
        self.assertIn("آذر", info)
        with tempfile.TemporaryDirectory() as d:
            res = p.generate(1405, 9, d)
            self.assertEqual(res.ok_count, 30)
            self.assertTrue(os.path.exists(res.zip_path))

    def test_tgs_flow_and_settings(self):
        p = Project()
        self.assertTrue(p.load(os.path.join(D, "gold_real.tgs")).startswith("✔"))
        p.scale_pct = 90
        p.kashida_override = 0
        im, info = p.preview(1405, 9, 1, 300)
        self.assertEqual(im.size, (300, 300))
        with tempfile.TemporaryDirectory() as d:
            res = p.generate(1405, 9, d)
            self.assertEqual(res.ok_count, 30, [(r.filename, r.messages) for r in res.failed])

    def test_bad_file_reports_error(self):
        p = Project()
        with tempfile.NamedTemporaryFile(suffix=".tgs") as f:
            f.write(b"not a tgs")
            f.flush()
            self.assertTrue(p.load(f.name).startswith("✘"))
        self.assertFalse(p.ok)

    def test_visual_rtl(self):
        v = visual("آبان 1405")
        self.assertTrue(v.startswith("1405"))                       # عدد در زمینه‌ی راست‌به‌چپ سمت چپ می‌رود
        self.assertTrue(all(ord(c) < 0x600 or ord(c) >= 0xFB50 or c == " " for c in v if not c.isdigit()))  # فرم‌های نمایشی


if __name__ == "__main__":
    unittest.main()
