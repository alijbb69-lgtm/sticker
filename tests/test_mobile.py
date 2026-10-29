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
        p.sizes = {"روز شمسی": 90}
        p.kash_user = {"روز هفته (فارسی)": 0}
        im, info = p.preview(1405, 9, 1, 300)
        self.assertEqual(im.size, (300, 300))
        with tempfile.TemporaryDirectory() as d:
            res = p.generate(1405, 9, d)
            self.assertEqual(res.ok_count, 30, [(r.filename, r.messages) for r in res.failed])

    def test_per_slot_settings_and_persistence(self):
        import json
        from src.mobile.core import load_state, save_state
        p = Project()
        p.load(os.path.join(D, "gold_static.png"))
        p.sizes = {"روز شمسی": 70}
        p.offsets = {"سال شمسی": (4, -2)}
        p.kash_user = {"روز هفته (فارسی)": 0}
        a, _ = p.preview(1405, 9, 1)
        p.sizes = {}
        p.offsets = {}
        b, _ = p.preview(1405, 9, 1)
        self.assertNotEqual(a.tobytes(), b.tobytes())
        with tempfile.TemporaryDirectory() as d:
            p.sizes = {"روز شمسی": 70}
            f = os.path.join(d, "s.json")
            save_state(p, f)
            q = Project()
            q.restore(load_state(f))
            self.assertEqual(q.sizes, {"روز شمسی": 70})
            self.assertTrue(q.ok and q.kind == "png")

    def test_png_manual_edit(self):
        p = Project()
        p.load(os.path.join(D, "gold_static.png"))
        asg = p.png_assign()
        p.png_set(asg, p.png_base())
        self.assertTrue(p.png_manual)
        self.assertIn("png", p.state())
        sg = p.png_suggest(p.png_base())
        self.assertTrue(sg)

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
