"""ویجت‌های نیومورفیسم: سطح برجسته/فرورفته با سایه‌ی نرم دوطرفه (با Pillow ساخته و کش می‌شود)."""
from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from . import theme
from .qtutil import pil_to_pixmap

_CACHE: dict = {}
theme.bus.changed.connect(_CACHE.clear)


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _rr(mask_size, box, radius, fill=255):
    im = Image.new("L", mask_size, 0)
    ImageDraw.Draw(im).rounded_rectangle(box, radius=max(0, radius), fill=fill)
    return im


def _tint(mask: Image.Image, rgba: tuple) -> Image.Image:
    img = Image.new("RGBA", mask.size, rgba[:3] + (0,))
    a = mask.point(lambda v: v * rgba[3] // 255)
    img.putalpha(a)
    return img


def raised_image(w, h, r, m, off, blur, light, dark, s) -> Image.Image:
    """فقط سایه‌ها (روشن بالا-چپ، تیره پایین-راست)؛ بدنه را QPainter می‌کشد."""
    W, H = (w + 2 * m) * s, (h + 2 * m) * s
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for rgba, d in ((light, -off), (dark, off)):
        box = (m * s + d * s, m * s + d * s, (m + w) * s - 1 + d * s, (m + h) * s - 1 + d * s)
        mask = _rr((W, H), box, r * s).filter(ImageFilter.GaussianBlur(blur * s / 2))
        out = Image.alpha_composite(out, _tint(mask, rgba))
    return out


def inset_image(w, h, r, m, off, blur, light, dark, body, s) -> Image.Image:
    """بدنه‌ی فرورفته با سایه‌ی داخلی."""
    W, H = (w + 2 * m) * s, (h + 2 * m) * s
    box = (m * s, m * s, (m + w) * s - 1, (m + h) * s - 1)
    body_mask = _rr((W, H), box, r * s)
    out = _tint(body_mask, body + (255,))
    for rgba, d in ((dark, off), (light, -off)):
        shifted = _rr((W, H), (box[0] + d * s, box[1] + d * s, box[2] + d * s, box[3] + d * s), r * s)
        inner = ImageChops.subtract(body_mask, shifted).filter(ImageFilter.GaussianBlur(blur * s / 2))
        inner = ImageChops.multiply(inner, body_mask)
        out = Image.alpha_composite(out, _tint(inner, rgba))
    return out


def shadow_pixmap(kind: str, w, h, r, m, off, blur, dpr: float, glow=None) -> QPixmap:
    p = theme.P
    s = 2 if dpr > 1.25 else 1
    key = (kind, w, h, r, m, off, blur, s, p.name, glow)
    pm = _CACHE.get(key)
    if pm is None:
        dark = glow if glow else p.dark
        if kind == "raised":
            im = raised_image(w - 2 * m, h - 2 * m, r, m, off, blur, p.light, dark, s)
        else:
            im = inset_image(w - 2 * m, h - 2 * m, r, m, off, blur, p.light, p.dark, _hex(p.field), s)
        pm = pil_to_pixmap(im, float(s))
        _CACHE[key] = pm
    return pm


class NeuSurface(QWidget):
    """کارت برجسته (یا فرورفته). بدنه با فاصله‌ی m از لبه است؛ از content_margins برای چیدن داخل استفاده کنید."""

    def __init__(self, radius=24, inset=False, margin=16, off=6, blur=14, pad=18, parent=None):
        super().__init__(parent)
        self.radius, self.inset, self.m, self.off, self.blur = radius, inset, margin, off, blur
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setContentsMargins(margin + pad, margin + pad, margin + pad, margin + pad)
        theme.bus.changed.connect(self.update)

    def body_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(self.m, self.m, -self.m, -self.m)

    def paintEvent(self, _e):
        if self.width() <= 2 * self.m or self.height() <= 2 * self.m:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pm = shadow_pixmap("inset" if self.inset else "raised", self.width(), self.height(), self.radius, self.m,
                           self.off, self.blur, self.devicePixelRatioF())
        p.drawPixmap(0, 0, pm)
        if not self.inset:
            _fill_body(p, self.body_rect(), self.radius)


def _fill_body(p: QPainter, rect: QRectF, radius: float, hover: bool = False):
    pal = theme.P
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    hi = QColor(pal.surface_hi)
    lo = QColor(pal.surface_lo)
    if hover:
        hi = hi.lighter(106)
        lo = lo.lighter(104)
    g.setColorAt(0, hi)
    g.setColorAt(1, lo)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(rect, radius, radius)


class NeuButton(QPushButton):
    """kind: plain | primary | round | tile | seg (قطعه‌ی انتخاب‌پذیر)."""

    def __init__(self, text="", kind="plain", parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self.icon_kind = ""
        self.accent_key = "accent"
        self.subtitle = ""
        self.done = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.NoFocus)
        if kind == "round":
            self.m, self.off, self.blur = 6, 3, 7
            self.setFixedSize(46, 46)
        elif kind == "tile":
            self.m, self.off, self.blur = 14, 7, 16
            self.setMinimumSize(172, 150)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        else:
            self.m, self.off, self.blur = 10, 5, 11
            self.setFixedHeight(66 if kind == "primary" else 62)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        theme.bus.changed.connect(self.update)

    def set_sub(self, text: str, done: bool = False):
        self.subtitle, self.done = text, done
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    # ------------------------------------------------------------------
    def _radius(self, rect: QRectF) -> float:
        return rect.height() / 2 if self.kind in ("plain", "primary", "round", "seg") else 26

    def paintEvent(self, _e):
        pal = theme.P
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h, m = self.width(), self.height(), self.m
        rect = QRectF(m, m, w - 2 * m, h - 2 * m)
        r = self._radius(rect)
        pressed = (self.isDown() or (self.isCheckable() and self.isChecked())) and self.isEnabled()
        dpr = self.devicePixelRatioF()
        enabled = self.isEnabled()
        if self.kind == "primary":
            glow = _hex(pal.accent2) + (120 if enabled else 40,)
            p.drawPixmap(0, 0, shadow_pixmap("raised", w, h, int(r), m, self.off, self.blur, dpr, glow=glow))
            g = QLinearGradient(rect.topLeft(), rect.bottomRight())
            c1, c2 = QColor(pal.accent), QColor(pal.accent2)
            if not enabled:
                c1.setAlpha(110)
                c2.setAlpha(110)
            elif self._hover:
                c1, c2 = c1.lighter(108), c2.lighter(106)
            if self.isDown():
                c1, c2 = c1.darker(108), c2.darker(108)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(rect, r, r)
            p.setPen(QColor("#ffffff"))
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSizeF(11.5)
            p.setFont(f)
            p.drawText(rect, Qt.AlignCenter, self.text())
            return
        if pressed:
            p.drawPixmap(0, 0, shadow_pixmap("inset", w, h, int(r), m, self.off, self.blur, dpr))
        else:
            p.drawPixmap(0, 0, shadow_pixmap("raised", w, h, int(r), m, self.off, self.blur, dpr))
            _fill_body(p, rect, r, self._hover and enabled)
        if self.kind == "tile":
            self._paint_tile(p, rect)
            return
        txt_col = QColor(pal.text if enabled else pal.muted)
        if self.kind == "seg" and self.isChecked():
            txt_col = QColor(pal.accent)
        if self.icon_kind:
            col = QColor(getattr(pal, self.accent_key))
            _draw_icon(p, self.icon_kind, rect, col)
        else:
            p.setPen(txt_col)
            f = QFont(self.font())
            if self.kind == "round":
                f.setPointSizeF(15)
                f.setBold(True)
                txt_col = QColor(pal.accent) if enabled else QColor(pal.muted)
                p.setPen(txt_col)
            elif self.kind == "seg":
                f.setBold(self.isChecked())
            p.setFont(f)
            p.drawText(rect, Qt.AlignCenter, self.text())

    def _paint_tile(self, p: QPainter, rect: QRectF):
        pal = theme.P
        rtl = self.isRightToLeft()
        pad = 20
        d = 52
        ix = rect.right() - pad - d if rtl else rect.left() + pad
        icon_rect = QRectF(ix, rect.top() + pad, d, d)
        col = QColor(getattr(pal, self.accent_key))
        g = QLinearGradient(icon_rect.topLeft(), icon_rect.bottomRight())
        g.setColorAt(0, col.lighter(115))
        g.setColorAt(1, col.darker(108))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(icon_rect)
        _draw_icon(p, self.icon_kind, icon_rect, QColor("#ffffff"))
        if self.done:
            dot = QRectF(rect.left() + pad if rtl else rect.right() - pad - 12, rect.top() + pad + 4, 12, 12)
            p.setBrush(QColor(pal.ok))
            p.drawEllipse(dot)
        tf = QFont(self.font())
        tf.setBold(True)
        tf.setPointSizeF(12)
        p.setFont(tf)
        p.setPen(QColor(pal.text))
        tx = QRectF(rect.left() + pad, icon_rect.bottom() + 14, rect.width() - 2 * pad, 26)
        al = Qt.AlignRight | Qt.AlignVCenter if rtl else Qt.AlignLeft | Qt.AlignVCenter
        p.drawText(tx, al, self.text())
        sf = QFont(self.font())
        sf.setPointSizeF(9)
        p.setFont(sf)
        p.setPen(QColor(pal.muted))
        fm = QFontMetrics(sf)
        sub = fm.elidedText(self.subtitle, Qt.ElideMiddle, int(rect.width() - 2 * pad))
        p.drawText(QRectF(rect.left() + pad, tx.bottom() + 2, rect.width() - 2 * pad, 24), al, sub)


def _draw_icon(p: QPainter, kind: str, rect: QRectF, col: QColor):
    """آیکن‌های برداری ساده داخل مستطیل rect."""
    c = rect.center()
    u = min(rect.width(), rect.height()) / 52.0     # واحد نسبت به دایره‌ی ۵۲ پیکسلی
    pen = QPen(col, 2.6 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.save()
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if kind == "template":
        r = QRectF(c.x() - 9 * u, c.y() - 12 * u, 18 * u, 24 * u)
        p.drawRoundedRect(r, 3 * u, 3 * u)
        p.drawLine(QPointF(r.left() + 4 * u, c.y() - 3 * u), QPointF(r.right() - 4 * u, c.y() - 3 * u))
        p.drawLine(QPointF(r.left() + 4 * u, c.y() + 3 * u), QPointF(r.right() - 4 * u, c.y() + 3 * u))
    elif kind == "font":
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(22 * u))
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, "Aa")
    elif kind == "month":
        r = QRectF(c.x() - 12 * u, c.y() - 10 * u, 24 * u, 22 * u)
        p.drawRoundedRect(r, 4 * u, 4 * u)
        p.drawLine(QPointF(r.left(), c.y() - 3 * u), QPointF(r.right(), c.y() - 3 * u))
        p.drawLine(QPointF(c.x() - 6 * u, r.top() - 3 * u), QPointF(c.x() - 6 * u, r.top() + 3 * u))
        p.drawLine(QPointF(c.x() + 6 * u, r.top() - 3 * u), QPointF(c.x() + 6 * u, r.top() + 3 * u))
    elif kind == "size":
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(13 * u))
        p.setFont(f)
        p.drawText(QRectF(c.x() - 14 * u, c.y() - 12 * u, 16 * u, 24 * u), Qt.AlignCenter, "A")
        f.setPixelSize(int(24 * u))
        p.setFont(f)
        p.drawText(QRectF(c.x() - 2 * u, c.y() - 14 * u, 18 * u, 28 * u), Qt.AlignCenter, "A")
    elif kind == "sun":
        p.drawEllipse(c, 5 * u, 5 * u)
        import math
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(c.x() + 9 * u * math.cos(a), c.y() + 9 * u * math.sin(a)),
                       QPointF(c.x() + 12 * u * math.cos(a), c.y() + 12 * u * math.sin(a)))
    elif kind == "moon":
        path = QPainterPath()
        path.addEllipse(c, 9 * u, 9 * u)
        cut = QPainterPath()
        cut.addEllipse(QPointF(c.x() + 5 * u, c.y() - 4 * u), 8 * u, 8 * u)
        p.drawPath(path.subtracted(cut))
    elif kind == "folder":
        r = QRectF(c.x() - 11 * u, c.y() - 7 * u, 22 * u, 15 * u)
        p.drawRoundedRect(r, 3 * u, 3 * u)
        p.drawLine(QPointF(r.left(), r.top() - 2 * u), QPointF(r.left() + 8 * u, r.top() - 2 * u))
    p.restore()


class Stepper(QWidget):
    """[ − ]  مقدار  [ + ] روی زمینه‌ی فرورفته؛ با texts به‌صورت انتخاب از فهرست (مثل ماه‌ها) کار می‌کند."""
    valueChanged = Signal(int)
    wrapped = Signal(int)

    def __init__(self, minimum=0, maximum=100, value=0, step=1, suffix="", texts=None, wrap=False, parent=None, prefix=""):
        super().__init__(parent)
        self._prefix = prefix
        self._min, self._max, self._step, self._suffix = minimum, maximum, step, suffix
        self._texts, self._wrap = texts, wrap
        if texts:
            self._min, self._max = 0, len(texts) - 1
        self._v = max(self._min, min(self._max, value))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(64)
        self.setAttribute(Qt.WA_StyledBackground, False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(6)
        self.plus = self._btn("+", +1)
        self.minus = self._btn("−", -1)
        self.label = QLabel(alignment=Qt.AlignCenter)
        self.label.setObjectName("stepperValue")
        lay.addWidget(self.plus)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.minus)
        theme.bus.changed.connect(self.update)
        self._refresh()

    def _btn(self, text, d):
        b = NeuButton(text, "round")
        b.setFixedSize(44, 44)
        b.setAutoRepeat(True)
        b.setAutoRepeatDelay(350)
        b.setAutoRepeatInterval(70)
        b.clicked.connect(lambda _=False, dd=d: self._bump(dd))
        return b

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.height() // 2 - 6
        m = 4
        pm = shadow_pixmap("inset", self.width(), self.height(), r + m, m, 4, 8, self.devicePixelRatioF())
        p.drawPixmap(0, 0, pm)

    def _bump(self, d):
        v = self._v + d * self._step
        if v > self._max or v < self._min:
            if not self._wrap:
                v = max(self._min, min(self._max, v))
            else:
                nv = self._min if v > self._max else self._max
                self._set(nv)
                self.wrapped.emit(+1 if v > self._max else -1)
                return
        self._set(v)

    def _set(self, v):
        if v != self._v:
            self._v = v
            self._refresh()
            self.valueChanged.emit(v)

    def _refresh(self):
        self.label.setText(self._texts[self._v] if self._texts else f"{self._prefix}{self._v}{self._suffix}")
        self.minus.setEnabled(self._wrap or self._v > self._min)
        self.plus.setEnabled(self._wrap or self._v < self._max)

    def value(self):
        return self._v

    def currentIndex(self):
        return self._v

    def setValue(self, v):
        self._v = max(self._min, min(self._max, int(v)))
        self._refresh()

    setCurrentIndex = setValue
