"""رشته‌ی پس‌زمینه‌ی تولید دسته‌ای (تا رابط کاربری هنگام تولید قفل نشود)."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..export.batch import BatchResult, generate_month
from ..png.engine import RasterEngine, encode_png, generate_month_png
from ..tgs.replacer import TemplateEngine


class BatchWorker(QThread):
    progress = Signal(int, int, str)
    finished_batch = Signal(object)      # BatchResult
    failed = Signal(str)

    def __init__(self, engine: TemplateEngine, jy: int, jm: int, out_dir: str, make_zip: bool, parent=None):
        super().__init__(parent)
        self.engine, self.jy, self.jm, self.out_dir, self.make_zip = engine, jy, jm, out_dir, make_zip
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            fn = generate_month_png if isinstance(self.engine, RasterEngine) else generate_month
            res: BatchResult = fn(
                self.engine, self.jy, self.jm, self.out_dir, self.make_zip,
                progress=lambda i, n, msg: self.progress.emit(i, n, msg),
                cancel=lambda: self._cancel)
            self.finished_batch.emit(res)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class PreviewJob(QThread):
    """ساخت استیکر پیش‌نمایش در پس‌زمینه (تغییر فونت/اندازه رابط را قفل نمی‌کند). نتیجه: (doc, گزارش‌ها, حجم بایت)."""
    done = Signal(object, object, int)
    failed = Signal(str)

    def __init__(self, doc: dict | None, slots: list, base_day, day, parent=None, png=None):
        super().__init__(parent)
        import copy
        self.doc, self.base_day, self.day, self.png = doc, base_day, day, png      # png = (PIL image, blobs)
        self.slots = copy.deepcopy(slots)          # کپی: رابط می‌تواند هم‌زمان تنظیمات را عوض کند

    def run(self):
        try:
            if self.png is not None:
                eng = RasterEngine(self.png[0], self.png[1], self.slots, self.base_day)
                out, reps = eng.generate(self.day)
                self.done.emit(out, reps, len(encode_png(out)))
                return
            from ..tgs.lottie_io import dump_tgs_bytes
            eng = TemplateEngine(self.doc, self.slots, self.base_day)
            out, reps = eng.generate(self.day)
            self.done.emit(out, reps, len(dump_tgs_bytes(out, 2)))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
