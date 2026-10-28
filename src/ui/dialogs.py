"""پنجره‌های چهارگانه: قالب، فونت‌ها، ماه، اندازه‌ها (هر کدام با کلیک روی کاشی مربوط باز می‌شود)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QScrollArea, QStackedWidget, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from . import theme
from .neu import NeuButton, NeuSurface, Stepper

SAMPLE_FA = "سلام، نمونه زیرنویس ۱۲۳"
SAMPLE_EN = "Hello, sample caption 123"


def _label(text="", name=None, wrap=True) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(wrap)
    if name:
        l.setObjectName(name)
    return l


class BaseDialog(QWidget):
    """صفحه‌ی درون‌پنجره‌ای (نه پاپ‌آپ): نوار بالا با دکمه‌ی بازگشت و عنوان، محتوا، دکمه‌ی «تأیید»."""
    finished = Signal()

    def __init__(self, parent, title: str, width=0, scroll=False):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(6, 4, 14, 8)
        self.root.setSpacing(14)
        top = QHBoxLayout()
        self.back = NeuButton("›", "round")
        self.back.setToolTip("بازگشت")
        self.back.clicked.connect(self.accept)
        top.addWidget(self.back)
        top.addWidget(_label(title, "heading", False), 1)
        self.root.addLayout(top)
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        if scroll:
            host = QWidget()
            host.setObjectName("page")
            host.setLayout(self.body)
            self.body.setContentsMargins(0, 0, 10, 0)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            area.setWidget(host)
            self.root.addWidget(area, 1)
        else:
            self.root.addLayout(self.body, 1)
        self.ok = NeuButton("تأیید", "primary")
        self.ok.clicked.connect(self.accept)
        self.root.addWidget(self.ok)

    def accept(self):
        self.finished.emit()


# ------------------------------------------------------------------ فونت
class _FontDelegate(QStyledItemDelegate):
    def __init__(self, sample: str, parent=None):
        super().__init__(parent)
        self.sample = sample
        self._fam: dict[str, str] = {}

    def family(self, path: str) -> str:
        fam = self._fam.get(path)
        if fam is None:
            fid = QFontDatabase.addApplicationFont(path)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            fam = fams[0] if fams else ""
            self._fam[path] = fam
        return fam

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 84)

    def paint(self, painter: QPainter, option, index):
        """هر ردیف دو خط جدا: بالا نام فونت، پایین متن نمونه (با فاصله‌ی کافی؛ هیچ‌وقت روی هم نمی‌افتند)."""
        pal = theme.P
        path = index.data(Qt.UserRole)
        name = index.data(Qt.DisplayRole)
        sel = bool(option.state & QStyle.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(option.rect).adjusted(4, 4, -4, -4)
        if sel:
            c = QColor(pal.accent)
            c.setAlpha(46)
            painter.setBrush(c)
            painter.setPen(QColor(pal.accent))
            painter.drawRoundedRect(r, 16, 16)
        inner = r.adjusted(20, 8, -20, -8)
        h1 = 22.0
        # خط اول: نام فونت (با فونت رابط، کوچک‌تر و خاموش‌تر)
        nf = QFont(option.font)
        nf.setBold(True)
        nf.setPointSizeF(9.5)
        painter.setFont(nf)
        painter.setPen(QColor(pal.accent if sel else pal.muted))
        fm = QFontMetrics(nf)
        painter.drawText(QRectF(inner.left(), inner.top(), inner.width(), h1), Qt.AlignRight | Qt.AlignVCenter,
                         fm.elidedText(name, Qt.ElideMiddle, int(inner.width())))
        # خط دوم: نمونه با خود فونت
        fam = self.family(path)
        sf = QFont(fam) if fam else QFont(option.font)
        sf.setPointSizeF(13)
        painter.setFont(sf)
        painter.setPen(QColor(pal.text))
        sm = QFontMetrics(sf)
        painter.drawText(QRectF(inner.left(), inner.top() + h1 + 4, inner.width(), inner.height() - h1 - 4),
                         Qt.AlignRight | Qt.AlignVCenter, sm.elidedText(self.sample, Qt.ElideRight, int(inner.width())))
        painter.restore()


class FontDialog(BaseDialog):
    """فونت شمسی، فونت میلادی و (اختیاری) فونت جداگانه برای هر متن؛ هر انتخاب همان لحظه اعمال می‌شود."""
    NONE = ""      # «طبق تنظیم کلی»

    def __init__(self, parent, fonts: list[str], fa_path: str, en_path: str, coverage_cb, on_change=None,
                 slot_names: list[str] | None = None, slot_fonts: dict | None = None):
        super().__init__(parent, "فونت‌ها", 640)
        self.fonts = list(fonts)
        self.sel = {"fa": fa_path, "en": en_path}
        self.slot_fonts = dict(slot_fonts or {})
        self.slot_names = list(slot_names or [])
        self.coverage_cb = coverage_cb
        self.on_change = on_change
        self.tab = "fa"
        seg = QHBoxLayout()
        seg.setSpacing(6)
        self.b_fa = NeuButton("شمسی", "seg")
        self.b_en = NeuButton("میلادی", "seg")
        self.b_sl = NeuButton("هر متن جدا", "seg")
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b, t in ((self.b_fa, "fa"), (self.b_en, "en"), (self.b_sl, "slot")):
            b.setCheckable(True)
            grp.addButton(b)
            seg.addWidget(b)
            b.clicked.connect(lambda _=False, tt=t: self._switch(tt))
        self.b_fa.setChecked(True)
        self.b_sl.setEnabled(bool(self.slot_names))
        self.body.addLayout(seg)
        self.slot_pick = Stepper(texts=self.slot_names or ["—"], wrap=True)
        self.slot_pick.valueChanged.connect(lambda _v: self._fill())
        self.slot_pick.setVisible(False)
        self.body.addWidget(self.slot_pick)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی فونت …")
        self.search.textChanged.connect(self._fill)
        self.body.addWidget(self.search)
        self.list = QListWidget()
        self.list.setMinimumHeight(240)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.delegate = _FontDelegate(SAMPLE_FA)
        self.list.setItemDelegate(self.delegate)
        # روی «فشردن» عمل می‌کند تا کلیک اول هم گرفته شود (نه فقط رها کردن)
        self.list.itemPressed.connect(self._picked)
        self.list.itemClicked.connect(self._picked)
        # کلیدهای ↑ ↓ (و PageUp/PageDown) هم همان لحظه اعمال شوند
        self.list.currentItemChanged.connect(lambda cur, _prev: self._picked(cur) if cur is not None else None)
        self.body.addWidget(self.list, 1)
        self.warn = _label(" ", "err")          # همیشه دیده می‌شود تا چیدمان جابه‌جا نشود
        self.warn.setMinimumHeight(40)
        self.body.addWidget(self.warn)
        add = NeuButton("افزودن فایل فونت (.ttf / .otf)", "plain")
        add.clicked.connect(self._browse)
        self.body.addWidget(add)
        self._fill()

    # --- وضعیت تب جاری
    def _slot(self) -> str:
        return self.slot_names[self.slot_pick.value()] if self.slot_names else ""

    def _current_path(self) -> str:
        if self.tab == "slot":
            return self.slot_fonts.get(self._slot(), self.NONE)
        return self.sel[self.tab]

    def _switch(self, tab: str):
        self.tab = tab
        self.slot_pick.setVisible(tab == "slot")
        self._fill()

    def _sample(self) -> str:
        if self.tab == "slot":
            n = self._slot()
            return SAMPLE_FA if ("شمسی" in n or "(فارسی)" in n) else SAMPLE_EN
        return SAMPLE_FA if self.tab == "fa" else SAMPLE_EN

    def _fill(self, *_):
        self.delegate.sample = self._sample()
        q = self.search.text().strip().lower()
        self.list.blockSignals(True)
        self.list.clear()
        cur = self._current_path()
        row = 0
        entries: list[tuple[str, str]] = []
        if self.tab == "slot":
            entries.append(("طبق تنظیم کلی (شمسی / میلادی)", self.NONE))
        entries += [(Path(p).stem, p) for p in self.fonts]
        for nm, p in entries:
            if q and q not in nm.lower() and p != self.NONE:
                continue
            it = QListWidgetItem(nm)
            it.setData(Qt.UserRole, p)
            self.list.addItem(it)
            if p == cur:
                row = self.list.count() - 1
                it.setSelected(True)
        if self.list.count():
            self.list.setCurrentRow(row)          # نقطه‌ی شروع کلیدهای جهت‌دار
            self.list.scrollToItem(self.list.item(row), QListWidget.PositionAtCenter)
        self.list.blockSignals(False)
        self._set_warn()

    def _picked(self, item):
        path = item.data(Qt.UserRole)
        if path == self._current_path():
            return
        if self.tab == "slot":
            if path == self.NONE:
                self.slot_fonts.pop(self._slot(), None)
            else:
                self.slot_fonts[self._slot()] = path
        else:
            self.sel[self.tab] = path
        self._notify()                       # اول اعمال روی استیکر…
        QTimer.singleShot(0, self._set_warn)  # …بعد بررسی پوشش حروف (کندتر)

    def _notify(self):
        if self.on_change:
            self.on_change(self.sel["fa"], self.sel["en"], dict(self.slot_fonts))

    def _set_warn(self):
        path = self._current_path()
        if not path:
            self.warn.setText(" ")
            return
        tab = self.tab
        if tab == "slot":
            n = self._slot()
            tab = "fa" if ("شمسی" in n or "(فارسی)" in n) else "en"
        self.warn.setText(self.coverage_cb(tab, path) or " ")

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "انتخاب فونت", "", "Fonts (*.ttf *.otf)")
        if p:
            if p not in self.fonts:
                self.fonts.insert(0, p)
            if self.tab == "slot":
                self.slot_fonts[self._slot()] = p
            else:
                self.sel[self.tab] = p
            self.search.clear()
            self._fill()
            self._notify()


# ------------------------------------------------------------------ قالب
class TemplateDialog(BaseDialog):
    def __init__(self, parent, open_cb, status_text: str, status_kind: str):
        super().__init__(parent, "قالب استیکر", 520)
        self.open_cb = open_cb
        btn = NeuButton("انتخاب فایل قالب (.tgs)", "plain")
        btn.icon_kind = ""
        btn.clicked.connect(self._open)
        self.body.addWidget(btn)
        self.status = _label(status_text or "هنوز قالبی انتخاب نشده است.", status_kind or "muted")
        self.body.addWidget(self.status)

    def _open(self):
        text, kind = self.open_cb(self)
        if text:
            self.status.setText(text)
            self.status.setObjectName(kind)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)


# ------------------------------------------------------------------ ماه
class MonthDialog(BaseDialog):
    def __init__(self, parent, months: list[str], jm: int, jy: int, on_change, info_cb):
        super().__init__(parent, "ماه و سال", 460)
        self.on_change, self.info_cb = on_change, info_cb
        self.month = Stepper(texts=months, value=jm - 1, wrap=True)
        self.year = Stepper(1300, 1700, jy)
        self.body.addWidget(_label("ماه", "muted", False))
        self.body.addWidget(self.month)
        self.body.addWidget(_label("سال", "muted", False))
        self.body.addWidget(self.year)
        self.info = _label("", "muted", False)
        self.body.addWidget(self.info)
        self.month.valueChanged.connect(self._changed)
        self.year.valueChanged.connect(self._changed)
        self.month.wrapped.connect(lambda d: (self.year.setValue(self.year.value() + d), self._changed()))
        self._changed(notify=False)

    def _changed(self, *_a, notify=True):
        jy, jm = self.year.value(), self.month.value() + 1
        self.info.setText(self.info_cb(jy, jm))
        if notify:
            self.on_change(jy, jm)


# ------------------------------------------------------------------ اندازه و جای نوشته‌ها
class SizesDialog(BaseDialog):
    """درصد اندازه‌ی هر متن و جابه‌جایی افقی/عمودی آن (پیکسل روی بوم ۵۱۲)."""

    def __init__(self, parent, names: list[str], sizes: dict[str, int], pos: dict[str, tuple], on_change, on_reset,
                 kashida: dict[str, int] | None = None, on_kashida=None):
        super().__init__(parent, "اندازه و جای نوشته‌ها", 620)
        self.on_kashida = on_kashida
        self.kash_sp: dict[str, Stepper] = {}
        kash_names = [n for n in names if n in ("روز هفته (فارسی)", "ماه شمسی")] if on_kashida else []
        self.on_change = on_change
        self.size_sp: dict[str, Stepper] = {}
        self.x_sp: dict[str, Stepper] = {}
        self.y_sp: dict[str, Stepper] = {}
        if not names:
            self.body.addWidget(_label("ابتدا یک قالب انتخاب کنید.", "muted"))
        seg = QHBoxLayout()
        seg.setSpacing(6)
        self.b_size = NeuButton("اندازه", "seg")
        self.b_pos = NeuButton("جابه‌جایی", "seg")
        self.b_kash = NeuButton("کشیدگی", "seg")
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in ((self.b_size, self.b_pos, self.b_kash) if kash_names else (self.b_size, self.b_pos)):
            b.setCheckable(True)
            grp.addButton(b)
            seg.addWidget(b)
        self.b_size.setChecked(True)
        self.body.addLayout(seg)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page(names, lambda n: self._mk_size(n, sizes), 2))
        self.stack.addWidget(self._page(names, lambda n: self._mk_pos(n, pos), 2))
        if kash_names:
            self.stack.addWidget(self._page(kash_names, lambda n: self._mk_kash(n, kashida or {}), 2))
            self.b_kash.clicked.connect(lambda: self._mode(2))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(self.stack)
        self.body.addWidget(sc, 1)
        self.hint = _label("", "muted")
        self.body.addWidget(self.hint)
        self.b_size.clicked.connect(lambda: self._mode(0))
        self.b_pos.clicked.connect(lambda: self._mode(1))
        self._mode(0)
        reset = NeuButton("بازگشت به حالت اصلی", "plain")

        def _r():
            for sp in self.size_sp.values():
                sp.setValue(100)
            for sp in list(self.x_sp.values()) + list(self.y_sp.values()):
                sp.setValue(0)
            on_reset()
        reset.clicked.connect(_r)
        reset.setEnabled(bool(names))
        self.body.addWidget(reset)

    def _mode(self, i: int):
        self.stack.setCurrentIndex(i)
        self.hint.setText("درصد اندازه‌ی هر متن نسبت به نوشته‌ی اصلی قالب." if i == 0 else
                          "↔ مثبت = به راست، ↕ مثبت = به پایین (پیکسل)." if i == 1 else
                          "کشیدگی حروف: ۰ = ساده، ۳ = شـــنـــبـــه. به‌طور خودکار از روی قالب حدس زده می‌شود.")

    def _page(self, names, make, cols):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 8, 0)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        for c in range(cols):
            g.setColumnStretch(c, 1)
        for k, n in enumerate(names):
            g.addWidget(make(n), k // cols, k % cols)
        g.setRowStretch(len(names) // cols + 1, 1)
        return w

    def _emit(self):
        sizes = {n: sp.value() for n, sp in self.size_sp.items()}
        pos = {n: (self.x_sp[n].value(), self.y_sp[n].value()) for n in self.x_sp}
        self.on_change(sizes, pos)

    def _mk_size(self, n, sizes):
        t = QWidget()
        lay = QVBoxLayout(t)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(_label(n, "muted", False))
        sp = Stepper(30, 300, sizes.get(n, 100), step=5, suffix="٪")
        sp.valueChanged.connect(lambda _v: self._emit())
        lay.addWidget(sp)
        self.size_sp[n] = sp
        return t

    def _mk_kash(self, n, kash):
        t = QWidget()
        lay = QVBoxLayout(t)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(_label(n, "muted", False))
        sp = Stepper(0, 6, kash.get(n, 0))
        sp.valueChanged.connect(lambda _v: self.on_kashida({k: w.value() for k, w in self.kash_sp.items()}))
        lay.addWidget(sp)
        self.kash_sp[n] = sp
        return t

    def _mk_pos(self, n, pos):
        t = QWidget()
        lay = QVBoxLayout(t)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(_label(n, "muted", False))
        x0, y0 = pos.get(n, (0, 0))
        sx = Stepper(-120, 120, x0, step=2, prefix="↔ ")
        sy = Stepper(-120, 120, y0, step=2, prefix="↕ ")
        for sp in (sx, sy):
            sp.valueChanged.connect(lambda _v: self._emit())
            lay.addWidget(sp)
        self.x_sp[n], self.y_sp[n] = sx, sy
        return t


# ------------------------------------------------------------------ استیکر ثابت (PNG): تعیین نوشته‌ها
class _ClickLabel(QLabel):
    clicked = Signal(float, float)          # مختصات داخل لیبل (px منطقی)

    def mousePressEvent(self, e):           # noqa: N802
        p = e.position() if hasattr(e, "position") else e.pos()
        self.clicked.emit(float(p.x()), float(p.y()))


class PngFieldsDialog(BaseDialog):
    """روی تصویر قالب کلیک می‌کنید تا ناحیه‌ی نوشته‌ی هر متغیر مشخص شود؛ تاریخِ نوشته‌شده روی استیکر را هم می‌دهید."""
    VIEW = 400

    def __init__(self, parent, img, blobs, slot_names: list[str], assign: dict, base_ymd: tuple, months: list[str],
                 suggest_cb, on_change):
        super().__init__(parent, "نوشته‌ها روی استیکر", 520, scroll=True)
        self.img, self.blobs = img.convert("RGBA"), list(blobs)
        self.names = slot_names
        self.assign = {k: tuple(v) for k, v in assign.items()}
        self.suggest_cb, self.on_change = suggest_cb, on_change
        self.scale = self.VIEW / max(self.img.size)
        self.body.addWidget(_label("۱) تاریخی را که الان روی این استیکر نوشته شده وارد کنید:", "muted"))
        self.day = Stepper(1, 31, base_ymd[2], suffix=" روز")
        self.month = Stepper(texts=months, value=base_ymd[1] - 1, wrap=True)
        self.year = Stepper(1300, 1700, base_ymd[0])
        for w in (self.day, self.month, self.year):
            self.body.addWidget(w)
            w.valueChanged.connect(self._date_changed)
        self.body.addWidget(_label("۲) یک متغیر را انتخاب کنید و روی نوشته‌ی مربوط در تصویر کلیک کنید:", "muted"))
        self.slot_pick = Stepper(texts=slot_names, wrap=True)
        self.slot_pick.valueChanged.connect(self._redraw)
        self.body.addWidget(self.slot_pick)
        self.pic = _ClickLabel(alignment=Qt.AlignCenter)
        self.pic.setCursor(Qt.PointingHandCursor)
        self.pic.clicked.connect(self._click)
        self.body.addWidget(self.pic, 0, Qt.AlignCenter)
        row = QHBoxLayout()
        self.digit_btn = NeuButton("", "plain")
        self.digit_btn.clicked.connect(self._toggle_digits)
        self.clear_btn = NeuButton("حذف این ناحیه", "plain")
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.digit_btn)
        row.addWidget(self.clear_btn)
        self.body.addLayout(row)
        auto = NeuButton("پیشنهاد خودکار", "plain")
        auto.clicked.connect(self._auto)
        self.body.addWidget(auto)
        self.info = _label("", "muted")
        self.body.addWidget(self.info)
        self._redraw()

    # ---- داده
    def base_ymd(self) -> tuple:
        return self.year.value(), self.month.value() + 1, self.day.value()

    def _cur(self) -> str:
        return self.names[self.slot_pick.value()]

    def _notify(self):
        self.on_change(dict(self.assign), self.base_ymd())

    def _date_changed(self, *_):
        self._notify()

    def _toggle_digits(self):
        n = self._cur()
        if n in self.assign:
            bid, dg = self.assign[n]
            self.assign[n] = (bid, "latin" if dg == "persian" else "persian")
            self._redraw()
            self._notify()

    def _clear(self):
        self.assign.pop(self._cur(), None)
        self._redraw()
        self._notify()

    def _auto(self):
        self.assign = {k: tuple(v) for k, v in self.suggest_cb(self.base_ymd()).items()}
        self._redraw()
        self._notify()

    def _click(self, x: float, y: float):
        ix, iy = x / self.scale, y / self.scale
        hit = [b for b in self.blobs if b.bbox[0] - 4 <= ix <= b.bbox[2] + 4 and b.bbox[1] - 4 <= iy <= b.bbox[3] + 4]
        if not hit:
            return
        b = min(hit, key=lambda b: (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]))
        n = self._cur()
        for k in [k for k, v in self.assign.items() if v[0] == b.id and k != n]:
            del self.assign[k]                       # هر ناحیه فقط به یک متغیر
        self.assign[n] = (b.id, self.assign.get(n, (None, "keep"))[1])
        self._redraw()
        self._notify()

    # ---- نمایش
    def _redraw(self, *_):
        from PIL import Image, ImageDraw

        from .qtutil import pil_to_pixmap
        W = self.VIEW * 2
        s = W / max(self.img.size)
        bg = Image.new("RGBA", self.img.size, (255, 255, 255, 255))
        bg.alpha_composite(self.img)
        im = bg.resize((int(self.img.width * s), int(self.img.height * s)), Image.LANCZOS)
        d = ImageDraw.Draw(im, "RGBA")
        cur = self._cur()
        by_blob = {v[0]: k for k, v in self.assign.items()}
        for b in self.blobs:
            x0, y0, x1, y1 = (v * s for v in b.bbox)
            own = by_blob.get(b.id)
            if own is None:
                d.rectangle([x0, y0, x1, y1], outline=(150, 150, 150, 170), width=2)
            else:
                col = (230, 40, 40, 255) if own == cur else (30, 140, 90, 255)
                d.rectangle([x0, y0, x1, y1], outline=col, width=5 if own == cur else 3, fill=col[:3] + (40,))
                d.text((x0 + 4, y0 + 2), str(self.names.index(own) + 1), fill=col)
        self.pic.setFixedSize(int(self.img.width * self.scale), int(self.img.height * self.scale))
        self.pic.setPixmap(pil_to_pixmap(im, 2.0))
        a = self.assign.get(cur)
        if a:
            self.info.setText(f"«{cur}» ← ناحیه‌ی {a[0].split('/')[-1]}")
            self.digit_btn.setText("ارقام: فارسی" if a[1] == "persian" else "ارقام: لاتین")
        else:
            self.info.setText(f"«{cur}» هنوز ناحیه‌ای ندارد (اگر در این استیکر نیست، خالی بگذارید).")
            self.digit_btn.setText("ارقام: —")
