import unittest

from src.vector_text.engine import contours_to_shape_items, layout_text
from src.vector_text.fonts import FontFace, default_font_path
from src.vector_text.shaping import joining_type, split_runs


class VectorTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.face = FontFace(default_font_path(True))

    def lay(self, text, **kw):
        return layout_text(text, self.face, self.face, **kw)

    def test_persian_words_produce_contours(self):
        for w in ("آبان", "شنبه", "یک‌شنبه", "جمعه", "اسفند", "فروردین"):
            lt = self.lay(w)
            self.assertTrue(lt.contours(), w)
            self.assertIsNotNone(lt.bbox(), w)

    def test_contextual_shaping_changes_glyphs(self):
        # «بب» متصل با «ب ب» جدا فرق دارد (شکل‌های اولیه/پایانی در برابر جدا)
        joined = self.lay("بب")
        apart = self.lay("ب ب")
        def sig(lt):
            return [round(c.v[0][0], 4) for g in lt.glyphs if g.contours for c in g.contours[:1]]
        self.assertNotEqual(sig(joined)[:1], sig(apart)[:1])
        self.assertNotEqual(joined.bbox()[2] - joined.bbox()[0], apart.bbox()[2] - apart.bbox()[0])

    def test_zwnj_breaks_joining(self):
        with_zwnj = self.lay("یک‌شنبه")
        without = self.lay("یکشنبه")
        self.assertNotEqual(len(with_zwnj.glyphs), 0)
        self.assertNotEqual(with_zwnj.bbox(), without.bbox())

    def test_rtl_order_is_right_to_left(self):
        # گلیف‌ها به ترتیب بصری (چپ به راست) هستند؛ اولین حرف منطقی «آ» باید راست‌ترین باشد
        lt = self.lay("آبان", base_dir="rtl")
        chars = [g.char for g in sorted(lt.glyphs, key=lambda g: g.x0)]
        self.assertEqual("".join(chars), "نابآ")

    def test_ltr_order(self):
        lt = self.lay("OCT", base_dir="ltr")
        xs = [g.x0 for g in lt.glyphs if g.contours]
        self.assertEqual(xs, sorted(xs))

    def test_digits_styles(self):
        a = self.lay("1405", digits="latin").bbox()
        b = self.lay("1405", digits="persian").bbox()
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b)

    def test_mixed_text(self):
        lt = self.lay("شنبه SATURDAY", base_dir="rtl")
        self.assertGreater(len(lt.contours()), 10)

    def test_lottie_items_are_closed_bezier(self):
        items = contours_to_shape_items(self.lay("24").contours(), nd=2)
        self.assertTrue(items)
        for it in items:
            self.assertEqual(it["ty"], "sh")
            v = it["ks"]["k"]
            self.assertTrue(v["c"])
            self.assertEqual(len(v["v"]), len(v["i"]))
            self.assertEqual(len(v["v"]), len(v["o"]))

    def test_joining_types(self):
        self.assertEqual(joining_type("ب"), "D")
        self.assertEqual(joining_type("ا"), "R")
        self.assertEqual(joining_type("‌"), "U")

    def test_split_runs_mixed(self):
        runs, _ = split_runs("شنبه SATURDAY", "rtl")
        self.assertGreaterEqual(len(runs), 2)


if __name__ == "__main__":
    unittest.main()


class SecondFontTests(unittest.TestCase):
    """آزمون با فونتی غیر از فونت همراه برنامه (در صورت وجود روی سیستم)."""
    CANDIDATES = ["/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
                  r"C:\Windows\Fonts\tahomabd.ttf", r"C:\Windows\Fonts\arialbd.ttf"]

    def test_other_font(self):
        import os
        path = next((p for p in self.CANDIDATES if os.path.exists(p)), None)
        if not path:
            self.skipTest("فونت دومی روی سیستم نیست")
        face = FontFace(path)
        lt = layout_text("آبان ۱۴۰۵", face, face, base_dir="rtl")
        self.assertTrue(lt.contours())
        self.assertIsNotNone(lt.bbox())
