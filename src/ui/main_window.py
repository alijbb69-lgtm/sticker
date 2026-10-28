"""پنجره‌ی اصلی: چهار کاشی (قالب، فونت‌ها، ماه، اندازه‌ها) + ساخت استیکرها؛ هر کاشی پنجره‌ی خودش را باز می‌کند."""
from __future__ import annotations

import os
from pathlib import Path

import json

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
                               QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ..calendars.jalali import JALALI_MONTHS_FA, day_info
from ..tgs.analyzer import analyze
from ..tgs.autodetect import detect, detect_best
from ..tgs.lottie_io import dump_tgs_bytes, load_tgs
from ..png.blobs import find_blobs, to_candidates
from ..png.engine import PNG_MAX_BYTES, RasterEngine
from ..png.session import load_session, stale_slots
from ..png.setup import apply_assignment, suggest
from ..tgs.replacer import TemplateEngine, default_slots, fit_kashida
from ..vector_text.fonts import FontFace, default_font_path, list_font_files
from . import theme
from .dialogs import FontDialog, MonthDialog, PngFieldsDialog, SizesDialog, TemplateDialog
from .neu import NeuButton
from .preview import PreviewWidget
from .workers import BatchWorker, PreviewJob

APP_TITLE = "Telegram Date Studio"
FA_PROBE = "آبانشنبهیکجمعهاسفند۰۱۲۳۴۵۶۷۸۹"
EN_PROBE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# سیستم فاصله‌گذاری (شبکه‌ی ۴ پیکسلی)
WIN_MARGIN = 26
COL_GAP = 24
GAP = 6          # فاصله‌ی بین کاشی‌ها (سایه‌ها خودشان حاشیه دارند)


def _label(text="", name=None, wrap=True) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(wrap)
    if name:
        l.setObjectName(name)
    return l


def _set_msg(lbl: QLabel, text: str, name: str | None = None):
    lbl.setText(text)
    lbl.setVisible(bool(text))
    if name and lbl.objectName() != name:
        lbl.setObjectName(name)
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1060, 760)
        self.setMinimumSize(980, 700)
        self.doc: dict | None = None
        self.slots: list = []
        self.base_day = None
        self.engine: TemplateEngine | None = None
        self.worker: BatchWorker | None = None
        self.out_dir: str | None = None
        self.last_out: str | None = None
        self.default_font = default_font_path(True)
        self.fonts = [self.default_font] + [p for p in list_font_files() if p != self.default_font]
        self.fa_path = self.default_font
        self.en_path = self.default_font
        self.jy, self.jm = 1405, 8
        self.tpl_name = ""
        self.tpl_msg, self.tpl_kind = "", "muted"
        self.size_values: dict[str, int] = {}
        self.offsets: dict[str, tuple] = {}
        self.slot_fonts: dict[str, str] = {}
        self.tpl_path = ""
        self.png_img = None                       # استیکر ثابت: تصویر PIL، ناحیه‌ها، نگاشت و تاریخِ نوشته‌شده
        self.png_blobs: list = []
        self.png_cands: list = []
        self.png_pre: dict = {}
        self.png_assign: dict[str, tuple] = {}
        self.png_base: tuple = (1405, 8, 1)
        self.png_hash = ""
        self.png_manual = False                    # فقط اصلاح دستیِ کاربر ذخیره و دوباره استفاده می‌شود
        self.png_saved: dict | None = None
        self.kashida: dict[str, int] = {}          # حدسِ خودکار از روی قالب
        self.kash_user: dict[str, int] = {}        # تنظیم دستیِ کاربر (اولویت دارد)
        self._cands: list = []
        self._job: PreviewJob | None = None
        self._job_dirty = False
        self.cfg = QSettings("TelegramDateStudio", "App")
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.timeout.connect(self._apply_sizes)

        root = QWidget()
        root.setObjectName("root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(WIN_MARGIN, WIN_MARGIN, WIN_MARGIN, WIN_MARGIN)
        outer.setSpacing(COL_GAP)

        # ----- ستون راست: عنوان، چهار کاشی، ساخت
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_label("Telegram Date Studio", "title", False))
        titles.addWidget(_label("ساخت استیکر تاریخ برای یک ماه کامل", "subtitle", False))
        head.addLayout(titles, 1)
        self.mode_btn = NeuButton("", "round")
        self.mode_btn.setToolTip("تم روشن / شب")
        self.mode_btn.clicked.connect(self.toggle_theme)
        head.addWidget(self.mode_btn, 0, Qt.AlignTop)
        col.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(GAP)
        self.t_tpl = self._tile("قالب", "template", "accent", self.dlg_template)
        self.t_font = self._tile("فونت‌ها", "font", "violet", self.dlg_fonts)
        self.t_month = self._tile("ماه و سال", "month", "teal", self.dlg_month)
        self.t_size = self._tile("اندازه‌ها", "size", "pink", self.dlg_sizes)
        grid.addWidget(self.t_tpl, 0, 0)
        grid.addWidget(self.t_font, 0, 1)
        grid.addWidget(self.t_month, 1, 0)
        grid.addWidget(self.t_size, 1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        col.addLayout(grid, 1)

        self.fields_btn = NeuButton("تعیین نوشته‌ها روی استیکر ثابت", "plain")
        self.fields_btn.setVisible(False)
        self.fields_btn.clicked.connect(self.dlg_png_fields)
        col.addWidget(self.fields_btn)
        self.gen_btn = NeuButton("ساخت استیکرهای این ماه", "primary")
        self.gen_btn.setEnabled(False)
        self.gen_btn.clicked.connect(self.start_batch)
        col.addWidget(self.gen_btn)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        col.addWidget(self.progress)
        self.result_label = _label("", "muted")
        self.result_label.setVisible(False)
        col.addWidget(self.result_label)
        self.open_btn = NeuButton("باز کردن پوشه‌ی خروجی", "plain")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self.open_folder)
        col.addWidget(self.open_btn)

        host = QWidget()
        host.setObjectName("colHost")
        host.setLayout(col)
        col.setContentsMargins(0, 0, 8, 0)
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QScrollArea.NoFrame)
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left.setWidget(host)
        self.stack = QStackedWidget()
        self.stack.addWidget(left)
        self.stack.setFixedWidth(440)
        outer.addWidget(self.stack)

        # ----- پیش‌نمایش
        pv = QVBoxLayout()
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(10)
        self.preview = PreviewWidget()
        pv.addWidget(self.preview, 1)
        self.pv_status = _label("", "muted", False)
        self.pv_status.setAlignment(Qt.AlignCenter)
        self.pv_status.setVisible(False)
        pv.addWidget(self.pv_status)
        outer.addLayout(pv, 1)
        self.setCentralWidget(root)

        theme.bus.changed.connect(self._sync_mode_icon)
        self._sync_mode_icon()
        self._restore()
        self._refresh_tiles()
        self.refresh_preview()

    def _open_page(self, page, after=None):
        """صفحه را داخل همین پنجره نشان می‌دهد؛ با «تأیید/بازگشت» به صفحه‌ی اصلی برمی‌گردد."""
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

        def _close():
            self.stack.setCurrentIndex(0)
            self.stack.removeWidget(page)
            page.deleteLater()
            if after:
                after()
            self._refresh_tiles()
        page.finished.connect(_close)

    # ---------------------------------------------------------------- کاشی‌ها و تم
    def _tile(self, title: str, icon: str, accent: str, slot) -> NeuButton:
        b = NeuButton(title, "tile")
        b.icon_kind, b.accent_key = icon, accent
        b.clicked.connect(slot)
        return b

    def _sync_mode_icon(self):
        self.mode_btn.icon_kind = "sun" if theme.P.name == "dark" else "moon"
        self.mode_btn.update()

    def toggle_theme(self):
        from PySide6.QtWidgets import QApplication
        theme.set_mode(QApplication.instance(), "light" if theme.P.name == "dark" else "dark")

    def _refresh_tiles(self):
        self.t_tpl.set_sub(self.tpl_name or "انتخاب نشده", self.has_tpl())
        self.t_font.set_sub(f"{Path(self.fa_path).stem} · {Path(self.en_path).stem}", True)
        self.t_month.set_sub(f"{JALALI_MONTHS_FA[self.jm - 1]} {self.jy}", True)
        n = len([s for s in self.slots if s.mapped and "(کپی" not in s.name])
        self.t_size.set_sub(f"{n} نوشته" if n else "پس از انتخاب قالب", bool(n))

    # ---------------------------------------------------------------- ذخیره/بازیابی تنظیمات
    def _save_settings(self):
        try:
            st = {"fa": self.fa_path, "en": self.en_path, "over": self.slot_fonts, "jy": self.jy, "jm": self.jm,
                  "tpl": self.tpl_path, "png": ({"hash": self.png_hash, "manual": True, "assign": {k: list(v) for k, v in self.png_assign.items()}, "base": list(self.png_base)} if (self.png_manual and self.png_img is not None) else None), "kash": self.kash_user, "sizes": self.size_values, "out": self.out_dir or "",
                  "pos": {k: list(v) for k, v in self.offsets.items()}, "fonts": self.fonts[:200]}
            self.cfg.setValue("state", json.dumps(st, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass

    def _restore(self):
        try:
            st = json.loads(self.cfg.value("state", "") or "{}")
        except Exception:  # noqa: BLE001
            return
        ok = lambda p: bool(p) and os.path.exists(p)  # noqa: E731
        for p in st.get("fonts", []):
            if ok(p) and p not in self.fonts:
                self.fonts.append(p)
        if ok(st.get("fa")):
            self.fa_path = st["fa"]
        if ok(st.get("en")):
            self.en_path = st["en"]
        self.slot_fonts = {k: v for k, v in st.get("over", {}).items() if ok(v)}
        self.jy = int(st.get("jy", self.jy))
        self.jm = int(st.get("jm", self.jm))
        self.out_dir = st.get("out") or None
        self.kash_user = {k: int(v) for k, v in st.get("kash", {}).items()}
        if ok(st.get("tpl")):
            self.png_saved = st.get("png") or None
            self.size_values = {k: int(v) for k, v in st.get("sizes", {}).items()}
            self.offsets = {k: tuple(v) for k, v in st.get("pos", {}).items()}
            try:
                self.load_template(st["tpl"])
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- فونت‌ها
    @staticmethod
    def _coverage(path: str, probe: str) -> list[str]:
        face = FontFace(path)
        return [c for c in dict.fromkeys(probe) if not face.has_char(c) and not _has_presentation_form(face, c)]

    def _font_warning(self, tab: str, path: str) -> str:
        probe, what = (FA_PROBE, "حروف و ارقام فارسی") if tab == "fa" else (EN_PROBE, "حروف و ارقام انگلیسی")
        try:
            missing = self._coverage(path, probe)
        except Exception as e:  # noqa: BLE001
            return f"فونت خوانده نشد: {e}"
        return f"این فونت برخی {what} را ندارد ({' '.join(missing[:6])}). فونت دیگری انتخاب کنید." if missing else ""

    def dlg_fonts(self):
        names = [s.name for s in self.slots if s.mapped and "(کپی" not in s.name]
        d = FontDialog(self, self.fonts, self.fa_path, self.en_path, self._font_warning, self._font_live,
                       names, self.slot_fonts)

        def after():
            self.fonts = d.fonts
            self._font_live(d.sel["fa"], d.sel["en"], d.slot_fonts)
            self._save_settings()
        self._open_page(d, after)

    def _font_live(self, fa: str, en: str, slot_fonts: dict | None = None):
        """هر انتخاب فونت همان لحظه روی استیکر پیش‌نمایش اعمال می‌شود (کار سنگین در پس‌زمینه)."""
        slot_fonts = dict(slot_fonts or {})
        if (fa, en, slot_fonts) != (self.fa_path, self.en_path, self.slot_fonts):
            self.fa_path, self.en_path, self.slot_fonts = fa, en, slot_fonts
            self.on_font_changed()

    def _apply_slot_settings(self):
        """فونت (گروهی و اختصاصی)، اندازه و جابه‌جایی را روی همه‌ی اسلات‌ها (و کپی‌های سایه) اعمال می‌کند."""
        for s in self.slots:
            base = s.name.split(" (کپی")[0]
            own = self.slot_fonts.get(base)
            s.fa_font, s.en_font = (own, own) if own else (self.fa_path, self.en_path)
            s.scale_mul = self.size_values.get(base, 100) / 100.0
            s.dx, s.dy = self.offsets.get(base, (0, 0))
            s.kashida = int(self.kash_user.get(base, self.kashida.get(base, 0)))

    def on_font_changed(self, *_):
        self._apply_slot_settings()
        self.engine = None
        self.refresh_preview()

    # ---------------------------------------------------------------- قالب
    def dlg_template(self):
        self._open_page(TemplateDialog(self, self.open_template, self.tpl_msg, self.tpl_kind))

    def open_template(self, parent=None) -> tuple[str, str]:
        path, _ = QFileDialog.getOpenFileName(parent or self, "انتخاب قالب", "", "استیکر (*.tgs *.png);;TGS متحرک (*.tgs);;PNG ثابت (*.png);;همه‌ی فایل‌ها (*)")
        if not path:
            return "", ""
        self.size_values, self.offsets, self.png_assign, self.kash_user, self.png_saved = {}, {}, {}, {}, None
        return self.load_template(path)

    def has_tpl(self) -> bool:
        return bool(self.doc) or self.png_img is not None

    def load_png(self, path: str) -> tuple[str, str]:
        try:
            ss = load_session(path, self.default_font, self.default_font, self.png_saved)
        except Exception as e:  # noqa: BLE001
            return self._bad_template(f"تصویر خوانده نشد: {e}")
        im = ss.img
        self.doc, self.engine = None, None
        self.png_img, self.png_blobs, self.png_cands, self.png_pre = ss.img, ss.blobs, ss.cands, ss.pre
        self.slots, self.base_day, self.png_assign = ss.slots, ss.base_day, ss.assign
        self.png_base = (ss.base_day.jy, ss.base_day.jm, ss.base_day.jd)
        self.png_hash, self.png_manual = ss.digest, not ss.auto
        self.kashida = ss.kashida
        self.tpl_name, self.tpl_path = Path(path).name, path
        msg = f"✔ {self.tpl_name} (استیکر ثابت)\n" + "\n".join(ss.notes) + "\nتشخیص: " + ss.summary() + self._kashida_note()
        un = ss.unmapped()
        if un:
            msg += "\n⚠ در این استیکر پیدا نشد (تغییر نمی‌کند): " + "، ".join(un)
        try:
            from ..calendars.jalali import day_info as _di
            bad = stale_slots(RasterEngine(ss.img, ss.blobs, ss.slots, ss.base_day), _di(1405, 8, 1), _di(1405, 9, 2))
        except Exception:  # noqa: BLE001
            bad = []
        if bad:
            msg += "\n⚠ این متن‌ها با عوض‌شدن تاریخ تغییر نمی‌کنند (نگاشت را اصلاح کنید): " + "، ".join(bad)
        if im.size != (512, 512) and max(im.size) != 512:
            msg += "\n⚠ استیکر تلگرام باید یک ضلعش دقیقاً ۵۱۲ باشد؛ این تصویر چنین نیست."
        self.tpl_msg, self.tpl_kind = msg, "ok"
        self.fields_btn.setVisible(True)
        self.gen_btn.setEnabled(True)
        _set_msg(self.result_label, "")
        self.open_btn.setVisible(False)
        self.on_font_changed()
        self._save_settings()
        return self.tpl_msg, self.tpl_kind

    def _auto_kashida(self, blobs=None):
        """اگر نوشته‌ی قالب کشیده است (شـنـبـه)، همین کشیدگی برای همه‌ی روزها/ماه‌ها اعمال می‌شود."""
        asp = {}
        for sl in self.slots:
            if not sl.mapped:
                continue
            if blobs is not None:
                b = next((x for x in blobs if x.id == sl.candidate_id), None)
                if b:
                    asp[sl.name] = (b.bbox[2] - b.bbox[0]) / max(b.bbox[3] - b.bbox[1], 1)
            elif self.doc is not None:
                c = next((x for x in self._cands if x.id == sl.candidate_id), None)
                if c is not None and c.world_bbox:
                    w, h = c.world_bbox[2] - c.world_bbox[0], c.world_bbox[3] - c.world_bbox[1]
                    if h > 1e-6:
                        asp[sl.name] = w / h
        self.kashida = fit_kashida(self.slots, self.base_day, asp)
        for sl in self.slots:
            sl.kashida = 0

    def _kashida_note(self) -> str:
        return ("\nنوشته‌ی کشیده‌ی قالب (" + "، ".join(f"{k} ←{v}" for k, v in self.kashida.items()) + ") برای همه‌ی روزها حفظ می‌شود."
                if self.kashida else "")

    def dlg_png_fields(self):
        if self.png_img is None:
            return
        names = [s.name for s in self.slots]
        months = list(JALALI_MONTHS_FA)
        suggest_cb = lambda ymd: suggest(self.slots, self.png_pre, day_info(*ymd))  # noqa: E731

        def changed(assign, ymd):
            self.png_assign, self.png_base, self.png_manual = dict(assign), tuple(ymd), True
            try:
                self.base_day = day_info(*self.png_base)
            except Exception:  # noqa: BLE001
                return
            apply_assignment(self.slots, self.png_assign, self.png_cands)
            self._refresh_tiles()
            self._size_timer.start(150)

        self._open_page(PngFieldsDialog(self, self.png_img, self.png_blobs, names, self.png_assign, self.png_base,
                                        months, suggest_cb, changed), lambda: self._save_settings())

    def load_template(self, path: str) -> tuple[str, str]:
        if path.lower().endswith((".png", ".webp")):
            return self.load_png(path)
        self.png_img = None
        self.fields_btn.setVisible(False)
        try:
            doc = load_tgs(path)
        except Exception as e:  # noqa: BLE001
            return self._bad_template(f"فایل خوانده نشد: {e}")
        try:
            slots, det = detect_best(doc, analyze(doc), self.default_font, self.default_font)
        except Exception as e:  # noqa: BLE001
            return self._bad_template(f"تحلیل قالب ناموفق بود: {e}")
        if not det.ok:
            return self._bad_template(det.message)
        self.doc, self.slots, self.base_day, self.engine = doc, slots, det.base_day, None
        self._cands = analyze(doc)
        self._auto_kashida(None)
        self.tpl_name = Path(path).name
        self.tpl_path = path
        missing = self._missing()
        msg = f"✔ {self.tpl_name}\n{det.message}"
        absent = [s.name for s in slots if not s.mapped and s.name not in missing]
        if absent:
            msg += "\nدر این قالب نیست (اضافه نمی‌شود): " + "، ".join(absent)
        if missing:
            msg += "\n⚠ پیدا نشد (تغییر نمی‌کند): " + "، ".join(missing)
        self.tpl_msg, self.tpl_kind = msg, ("err" if missing else "ok")
        self.gen_btn.setEnabled(True)
        _set_msg(self.result_label, "")
        self.open_btn.setVisible(False)
        self.on_font_changed()
        self._save_settings()
        return self.tpl_msg, self.tpl_kind

    def _missing(self) -> list[str]:
        """بخش‌های لازمِ پیدا‌نشده. اگر قالب روز هفته را فقط به یک زبان (یا اصلاً) ندارد، لازم نیست."""
        miss = [s.name for s in self.slots if not s.mapped and not s.name.startswith("روز هفته")]
        wd = [s for s in self.slots if s.name.startswith("روز هفته")]
        if self.png_img is not None and wd and not any(s.mapped for s in wd):
            miss.append("روز هفته")           # استیکرِ ثابت: اگر هیچ روز هفته‌ای پیدا نشد، بی‌صدا رد نشود
        return miss

    def _bad_template(self, msg: str) -> tuple[str, str]:
        self.doc, self.engine, self.slots, self.png_img = None, None, [], None
        self.fields_btn.setVisible(False)
        self.tpl_name = ""
        self.gen_btn.setEnabled(False)
        self.preview.set_doc(None)
        _set_msg(self.pv_status, "")
        self.tpl_msg, self.tpl_kind = "✘ " + msg, "err"
        return self.tpl_msg, self.tpl_kind

    # ---------------------------------------------------------------- ماه
    def _greg_info(self, jy: int, jm: int) -> str:
        d1 = day_info(jy, jm, 1)
        return f"۱ {d1.jalali_month_fa} = {d1.date.day} {d1.gregorian_month_en.capitalize()} {d1.date.year}"

    def dlg_month(self):
        self._open_page(MonthDialog(self, list(JALALI_MONTHS_FA), self.jm, self.jy, self._month_changed,
                                    self._greg_info))

    def _month_changed(self, jy: int, jm: int):
        self.jy, self.jm = jy, jm
        self._refresh_tiles()
        self.refresh_preview()
        self._save_settings()

    # ---------------------------------------------------------------- اندازه‌ها
    def dlg_sizes(self):
        names = [s.name for s in self.slots if s.mapped and "(کپی" not in s.name]
        eff = {n: self.kash_user.get(n, self.kashida.get(n, 0)) for n in names}
        self._open_page(SizesDialog(self, names, self.size_values, self.offsets, self._sizes_changed,
                                    self._reset_sizes, eff, self._kashida_changed), lambda: self._save_settings())

    def _sizes_changed(self, values: dict, offsets: dict):
        self.size_values, self.offsets = dict(values), {k: tuple(v) for k, v in offsets.items()}
        self._size_timer.start(120)

    def _kashida_changed(self, values: dict):
        self.kash_user = {k: int(v) for k, v in values.items()}
        self._size_timer.start(120)

    def _reset_sizes(self):
        self.size_values, self.offsets, self.kash_user = {}, {}, {}
        self._apply_sizes()

    def _apply_sizes(self):
        self._apply_slot_settings()
        self.engine = None
        self.refresh_preview()

    # ---------------------------------------------------------------- پیش‌نمایش و ساخت
    def ensure_engine(self) -> TemplateEngine | None:
        if not self.has_tpl():
            return None
        if self.engine is None:
            try:
                self._apply_slot_settings()
                if self.png_img is not None:
                    self.engine = RasterEngine(self.png_img, self.png_blobs, self.slots, self.base_day)
                else:
                    self.engine = TemplateEngine(self.doc, self.slots, self.base_day)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "خطا", str(e))
                return None
        return self.engine

    def refresh_preview(self, *_):
        """پیش‌نمایش روز اول ماه را در پس‌زمینه می‌سازد؛ درخواست‌های پشت‌سرهم ادغام می‌شوند (فقط آخری اجرا می‌شود)."""
        if not self.has_tpl():
            return
        if self._job is not None and self._job.isRunning():
            self._job_dirty = True
            return
        self._apply_slot_settings()
        d1 = day_info(self.jy, self.jm, 1)
        self._job_day = d1
        job = PreviewJob(self.doc, self.slots, self.base_day, d1, self,
                         png=(self.png_img, self.png_blobs) if self.png_img is not None else None)
        job.done.connect(self._preview_done)
        job.failed.connect(lambda m: _set_msg(self.pv_status, "⚠ " + m, "err"))
        job.finished.connect(self._job_finished)
        self._job = job
        job.start()

    def _job_finished(self):
        if self._job_dirty:
            self._job_dirty = False
            self._job = None
            self.refresh_preview()

    def _preview_done(self, doc, reps, nbytes: int):
        if self._job_dirty:         # نتیجه‌ی کهنه؛ اجرای بعدی جایگزینش می‌شود
            return
        is_png = self.png_img is not None
        (self.preview.set_image if is_png else self.preview.set_doc)(doc)
        d1 = self._job_day
        bad = [r for r in reps if not r.ok]
        kb = nbytes / 1024
        limit = PNG_MAX_BYTES // 1024 if is_png else 64
        size_txt = f"حجم ≈ {kb:.0f} KB از {limit}"
        if bad:
            _set_msg(self.pv_status, "⚠ " + "، ".join(f"{r.slot}: {'; '.join(r.warnings)[:80]}" for r in bad), "err")
        elif kb > limit:
            _set_msg(self.pv_status, f"⚠ {size_txt} — بیش از حد مجاز تلگرام؛ هنگام ساخت خودکار سبک‌تر می‌شود",
                     "err")
        else:
            same = self.base_day is not None and (d1.jy, d1.jm, d1.jd) == (self.base_day.jy, self.base_day.jm, self.base_day.jd)
            _set_msg(self.pv_status, f"پیش‌نمایش روز اول: {d1.jd} {d1.jalali_month_fa} {d1.jy}   ·   {size_txt}"
                     + ("\n(همان تاریخِ نوشته‌شده روی قالب است؛ ماه دیگری را امتحان کنید تا تغییر را ببینید)" if same else ""),
                     "muted")

    def start_batch(self):
        if self.worker and self.worker.isRunning():
            return
        eng = self.ensure_engine()
        if not eng:
            return
        missing = self._missing()
        if missing:
            r = QMessageBox.question(self, "بخش‌های پیدا‌نشده",
                                     "این بخش‌ها در قالب پیدا نشدند و در همه‌ی استیکرها همان مقدار قدیمی می‌مانند:\n• "
                                     + "\n• ".join(missing) + "\n\nادامه می‌دهید؟")
            if r != QMessageBox.Yes:
                return
        base = QFileDialog.getExistingDirectory(self, "پوشه‌ی ذخیره‌ی استیکرها", self.out_dir or str(Path.home()))
        if not base:
            return
        self.out_dir = base
        self._save_settings()
        jy, jm = self.jy, self.jm
        out = os.path.join(base, f"{jy}-{jm:02d}")
        self.progress.setValue(0)
        self.gen_btn.setEnabled(False)
        _set_msg(self.result_label, "در حال ساخت …", "muted")
        self.worker = BatchWorker(eng, jy, jm, out, True, self)
        self.worker.progress.connect(lambda i, n, _m: (self.progress.setMaximum(n), self.progress.setValue(i)))
        self.worker.finished_batch.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _failed(self, msg: str):
        self.gen_btn.setEnabled(True)
        _set_msg(self.result_label, "✘ " + msg, "err")

    def _done(self, res):
        self.gen_btn.setEnabled(True)
        total = len(res.results)
        txt = f"{res.ok_count} از {total} استیکر معتبر ساخته شد.\n{res.out_dir}"
        if res.failed:
            first = res.failed[0]
            txt += f"\n✘ {len(res.failed)} فایل نامعتبر بود: {first.filename} — {'; '.join(first.messages)[:140]}"
            txt += "\n(جزئیات در report.txt)"
        _set_msg(self.result_label, txt, "err" if res.failed else "ok")
        self.last_out = res.out_dir
        self.open_btn.setVisible(True)

    def open_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if self.last_out:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_out))


def _has_presentation_form(face: FontFace, ch: str) -> bool:
    import unicodedata
    for cp in range(0xFB50, 0xFF00):
        d = unicodedata.decomposition(chr(cp)).split()
        if d and d[-1] == f"{ord(ch):04X}" and face.has_char(chr(cp)):
            return True
    return False
