import copy
import gzip
import json
import os
import tempfile
import unittest

from src.calendars.jalali import day_info, month_days
from src.export.batch import generate_month
from src.tgs.analyzer import analyze, get_comps
from src.tgs.lottie_io import TGS_MAX_BYTES, dump_tgs_bytes, load_tgs_bytes
from src.tgs.replacer import TemplateEngine, auto_map, default_slots
from src.tgs.sample_template import build_sample_template
from src.validation.validator import validate_bytes
from src.vector_text.fonts import default_font_path


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp = default_font_path(True)
        cls.doc = build_sample_template(cls.fp)
        cls.base = day_info(1405, 8, 2)
        cls.cands = analyze(cls.doc)
        cls.slots = default_slots(cls.fp, cls.fp)
        auto_map(cls.doc, cls.cands, cls.slots, cls.base)
        cls.engine = TemplateEngine(cls.doc, cls.slots, cls.base)

    def test_all_slots_auto_mapped(self):
        self.assertTrue(all(s.mapped for s in self.slots), [s.name for s in self.slots if not s.mapped])
        keys = set()
        for s in self.slots:
            for m in s.members:
                k = (s.comp, s.layer_pos, tuple(s.container), m)
                self.assertNotIn(k, keys, "دو اسلات روی یک گروه")
                keys.add(k)

    def test_decorative_star_is_not_mapped(self):
        # ستاره یک گروه مسیری با fill است اما متن نیست
        star_layer = next(i for i, l in enumerate(self.doc["layers"]) if l["nm"] == "Shape Layer 3")
        for s in self.slots:
            self.assertNotEqual(s.layer_pos, star_layer)

    def test_generate_many_days_valid(self):
        for jd in (1, 2, 3, 15, 29, 30):
            day = day_info(1405, 8, jd)
            doc, reps = self.engine.generate(day)
            data = dump_tgs_bytes(doc)
            res = validate_bytes(data, reps)
            self.assertTrue(res.ok, [str(c) for c in res.errors])
            self.assertLessEqual(len(data), TGS_MAX_BYTES)

    def test_texts_differ_between_days(self):
        d1, _ = self.engine.generate(day_info(1405, 8, 1))
        d2, _ = self.engine.generate(day_info(1405, 8, 2))
        self.assertNotEqual(json.dumps(d1, sort_keys=True), json.dumps(d2, sort_keys=True))

    def test_unrelated_layers_untouched(self):
        out, _ = self.engine.generate(day_info(1405, 8, 9))
        mapped = {(s.comp, s.layer_pos) for s in self.slots}
        for i, (a, b) in enumerate(zip(self.doc["layers"], out["layers"])):
            if ("root", i) not in mapped:
                self.assertEqual(a, b, f"لایه‌ی غیرمرتبط {i} تغییر کرده")

    def test_styles_and_animation_preserved(self):
        out, _ = self.engine.generate(day_info(1405, 8, 9))
        for s in self.slots:
            la = self.doc["layers"][s.layer_pos]
            lb = out["layers"][s.layer_pos]
            self.assertEqual(la["ks"], lb["ks"])
            self.assertEqual(la.get("parent"), lb.get("parent"))
            self.assertEqual((la["ip"], la["op"]), (lb["ip"], lb["op"]))
        self.assertEqual([l["ind"] for l in self.doc["layers"]], [l["ind"] for l in out["layers"]])

        def non_path(items):
            r = []
            for it in items:
                if it.get("ty") == "sh":
                    continue
                r.append({**it, "it": non_path(it["it"])} if it.get("ty") == "gr" else it)
            return r
        # در لایه‌ی روز: fill و transform (با کی‌فریم pop) هر گروه همان است
        i = next(k for k, l in enumerate(self.doc["layers"]) if l["nm"] == "Shape Layer 5")
        la = non_path(self.doc["layers"][i]["shapes"])
        lb = non_path(out["layers"][i]["shapes"])
        self.assertEqual(la, lb)

    def test_cluster_gets_more_glyph_groups(self):
        # سال شمسی ۴ حرفی است؛ تاریخ بدون تغییر تعداد حرف، تعداد گروه ثابت می‌ماند
        out, reps = self.engine.generate(day_info(1405, 8, 9))
        year = next(r for r in reps if r.slot == "سال شمسی")
        self.assertEqual(len(year.members_after), 4)

    def test_no_text_layer_in_output(self):
        out, _ = self.engine.generate(day_info(1405, 8, 9))
        self.assertFalse(any(l["ty"] == 5 for l in out["layers"]))

    def test_batch_month(self):
        with tempfile.TemporaryDirectory() as d:
            b = generate_month(self.engine, 1405, 8, d)
            self.assertEqual(len(b.results), 30)
            self.assertEqual(b.ok_count, 30, [(r.filename, r.messages) for r in b.failed])
            self.assertTrue(os.path.exists(os.path.join(d, "1405-08-01.tgs")))
            self.assertTrue(os.path.exists(b.zip_path))
            self.assertTrue(os.path.exists(os.path.join(d, "report.txt")))
            with open(os.path.join(d, "1405-08-30.tgs"), "rb") as fh:
                data = fh.read()
            self.assertEqual(gzip.decompress(data)[:1], b"{")

    def test_esfand_leap_and_common(self):
        self.assertEqual(len(month_days(1403, 12)), 30)
        self.assertEqual(len(month_days(1405, 12)), 29)


class ValidatorNegativeTests(unittest.TestCase):
    def setUp(self):
        self.doc = build_sample_template(default_font_path(True))

    def check(self, doc, raw=None):
        return validate_bytes(raw if raw is not None else dump_tgs_bytes(doc), None)

    def test_valid_template_passes(self):
        self.assertTrue(self.check(self.doc).ok)

    def test_bad_gzip(self):
        self.assertFalse(validate_bytes(b"not gzip").ok)

    def test_bad_json(self):
        self.assertFalse(validate_bytes(gzip.compress(b"{oops")).ok)

    def test_wrong_canvas(self):
        d = copy.deepcopy(self.doc); d["w"] = 500
        self.assertFalse(self.check(d).ok)

    def test_fps_too_high(self):
        d = copy.deepcopy(self.doc); d["fr"] = 90
        self.assertFalse(self.check(d).ok)

    def test_too_long(self):
        d = copy.deepcopy(self.doc); d["op"] = 400
        self.assertFalse(self.check(d).ok)

    def test_text_layer_rejected(self):
        d = copy.deepcopy(self.doc)
        d["layers"].append({"ty": 5, "ind": 99, "nm": "t", "ks": {}, "ip": 0, "op": 180})
        self.assertFalse(self.check(d).ok)

    def test_oversize_rejected(self):
        d = copy.deepcopy(self.doc)
        import random
        rnd = random.Random(1)
        d["junk"] = [rnd.random() for _ in range(30000)]
        self.assertFalse(self.check(d).ok)


if __name__ == "__main__":
    unittest.main()
