"""پیش‌نمایش انیمیشن با کیفیت بالا (رندر ۲ برابر برای نمایش HiDPI + نرم‌سازی)، فریم‌ها در پس‌زمینه ساخته می‌شوند."""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from ..render.simple_renderer import Renderer
from .neu import NeuButton, NeuSurface
from .qtutil import pil_to_qimage

LOGICAL = 380          # اندازه‌ی نمایش (px منطقی)
SCALE = 2              # رندر با چگالی ۲ برابر → ۷۶۰px، سپس با نرم‌سازی نمایش داده می‌شود
SUPERSAMPLE = 2        # ضدلبه‌سازی داخل رندرر


class FrameWorker(QThread):
    frame_ready = Signal(int, int, object)     # generation, frame, QImage
    engine_ready = Signal(int, str)            # generation, "rlottie" | "approx"
    engine = "approx"

    def __init__(self, doc: dict, generation: int, order: list[int], parent=None):
        super().__init__(parent)
        self.doc, self.generation, self.order = doc, generation, order
        self._stop = False

    def stop(self):
        self._stop = True

    def _make_renderer(self):
        """rlottie (همان موتور تلگرام) اگر نصب باشد؛ وگرنه رندرر Pillow (تقریبی)."""
        size = LOGICAL * SCALE
        try:
            import json
            import rlottie_python  # type: ignore
            anim = rlottie_python.LottieAnimation.from_data(json.dumps(self.doc))
            anim.render_pillow_frame(0, size, size)       # آزمون سالم بودن
            self.engine = "rlottie"
            return lambda f: anim.render_pillow_frame(int(f), size, size)
        except Exception:
            r = Renderer(self.doc, size, SUPERSAMPLE)
            self.engine = "approx"
            return lambda f: r.render(float(f), bg=None)

    def run(self):
        render = self._make_renderer()
        self.engine_ready.emit(self.generation, self.engine)
        for f in self.order:
            if self._stop:
                return
            try:
                im = render(f)
            except Exception:
                return
            self.frame_ready.emit(self.generation, f, pil_to_qimage(im))


class PreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: dict | None = None
        self.frame = 0
        self.gen = 0
        self.worker: FrameWorker | None = None
        self._frames: dict[int, QPixmap] = {}

        frame = NeuSurface(radius=30, inset=True, margin=10, off=6, blur=14, pad=14)
        fl = QVBoxLayout(frame)
        self.label = QLabel(alignment=Qt.AlignCenter)
        self.label.setFixedSize(LOGICAL, LOGICAL)
        self.label.setStyleSheet("background: transparent;")
        fl.addWidget(self.label, 0, Qt.AlignCenter)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._on_slider)
        self.play_btn = NeuButton("▶", "round")
        self.play_btn.setCheckable(True)
        self.play_btn.toggled.connect(self._toggle_play)
        row = QHBoxLayout()
        row.addWidget(self.play_btn)
        row.addWidget(self.slider, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(frame, 1)
        lay.setSpacing(12)
        lay.addLayout(row)
        self.note = QLabel("پیش‌نمایش تقریبی است (فایل خروجی تحت تأثیر نیست). برای نمایش دقیق: pip install rlottie-python")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setVisible(False)
        lay.addWidget(self.note)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    def set_doc(self, doc: dict | None):
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.gen += 1
        self.doc = doc
        self._frames.clear()
        self.slider.setVisible(True)
        self.play_btn.setVisible(True)
        if doc is None:
            self.label.clear()
            return
        ip, op = int(doc.get("ip", 0)), int(doc.get("op", 60))
        last = max(ip, op - 1)
        self.slider.blockSignals(True)
        self.slider.setRange(ip, last)
        self.frame = max(ip, min(last, self.frame if self.frame else (ip + op) // 2))
        self.slider.setValue(self.frame)
        self.slider.blockSignals(False)
        # فریم فعلی اول، بعد بقیه
        order = [self.frame] + [f for f in range(ip, last + 1) if f != self.frame]
        self.worker = FrameWorker(doc, self.gen, order, self)
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.engine_ready.connect(self._on_engine)
        self.worker.start()

    def set_image(self, im):
        """استیکر ثابت (PIL RGBA): بدون اسلایدر/پخش، فقط تصویر."""
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.gen += 1
        self.doc = None
        self.timer.stop()
        self._frames.clear()
        self.slider.setVisible(False)
        self.play_btn.setVisible(False)
        self.note.setVisible(False)
        from .qtutil import pil_to_pixmap
        big = im.resize((LOGICAL * SCALE, LOGICAL * SCALE), 1) if im.size[0] == im.size[1] else im
        self.label.setPixmap(pil_to_pixmap(big, SCALE))

    def _on_engine(self, gen: int, engine: str):
        if gen == self.gen:
            self.note.setVisible(engine != "rlottie")

    def _on_frame(self, gen: int, f: int, qimg):
        if gen != self.gen:
            return
        pm = QPixmap.fromImage(qimg)
        pm.setDevicePixelRatio(SCALE)
        self._frames[f] = pm
        if f == self.frame:
            self._show()

    def _show(self):
        pm = self._frames.get(self.frame)
        if pm is not None:
            self.label.setPixmap(pm)

    def _on_slider(self, v: int):
        self.frame = v
        self._show()

    def _toggle_play(self, on: bool):
        self.play_btn.setText("⏸" if on else "▶")
        if on and self.doc:
            self.timer.start(int(1000 / max(1.0, float(self.doc.get("fr", 30)))))
        else:
            self.timer.stop()

    def _tick(self):
        if not self.doc:
            return
        ip, op = int(self.doc.get("ip", 0)), int(self.doc.get("op", 60))
        nxt = self.frame + 1
        nxt = ip if nxt >= op else nxt
        if nxt in self._frames:
            self.slider.setValue(nxt)
