"""ویجت‌های نیومورفیسم برای Kivy (همان ظاهر نسخه‌ی ویندوز): کارت، دکمه، کاشی، شمارنده‌ی ± ، تب، نوار پیشرفت، برچسب فارسی.
تصویرها با Pillow ساخته می‌شوند (src/mobile/neu_img.py) و به‌صورت بافت (texture) رسم می‌شوند."""
from __future__ import annotations

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from src.mobile import neu_img
from src.mobile.rtl import visual

FONT = "UI"                      # در main.py با LabelBase.register ثبت می‌شود
SCALE = 1.0                      # ضریب اندازه‌ی متن رابط (تنظیمات)


class Theme:
    pal = neu_img.LIGHT

    @classmethod
    def set(cls, mode: str):
        cls.pal = neu_img.DARK if mode == "dark" else neu_img.LIGHT
        _TEX.clear()

    @classmethod
    def c(cls, key: str, a: float = 1.0):
        if key == "text_on_accent":
            return (1, 1, 1, a)
        return neu_img.rgba01(getattr(cls.pal, key), a)


def S() -> float:
    return dp(1)


def mg() -> int:
    """حاشیه‌ی سایه‌ی کارت‌ها (پیکسل)."""
    return int(10 * S())


# ---------------------------------------------------------------- بافت‌ها
def to_texture(im) -> Texture:
    im = im.convert("RGBA")
    t = Texture.create(size=im.size, colorfmt="rgba")
    t.blit_buffer(im.tobytes(), colorfmt="rgba", bufferfmt="ubyte")
    t.flip_vertical()
    return t


_TEX: dict = {}


def skin_tex(kind: str, w: int, h: int, pressed=False, enabled=True) -> Texture:
    key = (kind, w, h, Theme.pal.name, pressed, enabled)
    t = _TEX.get(key)
    if t is None:
        if len(_TEX) > 250:
            _TEX.clear()
        t = to_texture(neu_img.make(kind, w, h, Theme.pal, S(), pressed, enabled))
        _TEX[key] = t
    return t


# ---------------------------------------------------------------- متن فارسی
def fa_wrap(text: str, max_w: float, fs: float, fn: str | None = None) -> str:
    """متن منطقی → رشته‌ی چندخطیِ قابل‌نمایش (شکستن خط بر پایه‌ی پهنای واقعی، سپس شکل‌دهی و ترتیب دیداری)."""
    cl = CoreLabel(font_name=fn or FONT, font_size=fs)

    def width(s: str) -> float:
        try:
            return cl.get_extents(s)[0]
        except Exception:  # noqa: BLE001
            return len(s) * fs * 0.55

    lines: list[str] = []
    for para in str(text).split("\n"):
        line = ""
        for w in para.split(" "):
            cand = f"{line} {w}" if line else w
            if not line or width(visual(cand)) <= max_w:
                line = cand
            else:
                lines.append(line)
                line = w
        lines.append(line)
    return "\n".join(visual(l) for l in lines)


class FaLabel(Label):
    """برچسب فارسی/انگلیسی: شکل‌دهی، راست‌به‌چپ و شکستن خط خودکار. ارتفاع به‌اندازه‌ی متن می‌شود (مگر auto_h=False)."""

    def __init__(self, text="", size=14, color="text", bold=False, align="right", wrap=True, auto_h=True, **kw):
        self.ltext = text
        self._wrap = wrap
        self._auto_h = auto_h
        self._ckey = color
        self._fs = sp(size) * SCALE
        if "size_hint" not in kw:
            kw.setdefault("size_hint_y", None if auto_h else 1)
        super().__init__(font_name=FONT, font_size=self._fs, color=Theme.c(color), halign=align, valign="middle",
                         bold=bold, **kw)
        self.bind(width=self._relayout)
        if not auto_h:
            self.bind(height=self._relayout)
        self._relayout()

    def set(self, text: str, color: str | None = None):
        self.ltext = text
        if color:
            self._ckey = color
            self.color = Theme.c(color)
        self._relayout()

    def _relayout(self, *_):
        w = self.width
        if w <= 4:
            return
        if self._wrap:
            self.text = fa_wrap(self.ltext, max(w - 2, 10), self._fs)
            self.text_size = (w, None) if self._auto_h else (w, self.height)
        else:
            self.text = visual(self.ltext)
            self.text_size = (w, None) if self._auto_h else (w, self.height)
        if self._auto_h:
            self.texture_update()
            self.height = max(self.texture_size[1] + dp(6), dp(24))


# ---------------------------------------------------------------- پوسته (سطح برجسته/فرورفته)
class SkinMixin:
    skin_kind = "card"

    def _init_skin(self, kind: str):
        self.skin_kind = kind
        self._pressed = False
        self._enabled = True
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self._skin_rect = Rectangle()
        self.bind(pos=self._skin_update, size=self._skin_update)

    def _skin_update(self, *_):
        w, h = int(self.width), int(self.height)
        if hasattr(self, "do_layout"):
            self.do_layout()
        if w < 8 or h < 8:
            return
        self._skin_rect.pos = self.pos
        self._skin_rect.size = (w, h)
        self._skin_rect.texture = skin_tex(self.skin_kind, w, h, self._pressed, self._enabled)

    def set_skin(self, kind=None, pressed=None, enabled=None):
        if kind is not None:
            self.skin_kind = kind
        if pressed is not None:
            self._pressed = pressed
        if enabled is not None:
            self._enabled = enabled
        self._skin_update()


class NeuBox(SkinMixin, BoxLayout):
    """کارت برجسته/فرورفته با محتوای عمودی. ارتفاع به‌اندازه‌ی محتواست (auto_h)."""

    def __init__(self, kind="card", pad=14, auto_h=True, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("spacing", dp(8))
        m = mg() + int(pad * S())
        kw.setdefault("padding", [m, m, m, m])
        if auto_h:
            kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self._init_skin(kind)
        if auto_h:
            self.bind(minimum_height=self.setter("height"))


class NeuButton(ButtonBehavior, SkinMixin, BoxLayout):
    """kind: plain | primary | round | seg | tile."""

    def __init__(self, text="", kind="plain", size=15, color=None, **kw):
        h = {"primary": 70, "plain": 62, "round": 56, "seg": 56}.get(kind, 60)
        if kind == "round":
            kw.setdefault("size_hint", (None, None))
            kw.setdefault("size", (dp(h) + 2 * mg() - dp(14), dp(h) + 2 * mg() - dp(14)))
        else:
            kw.setdefault("size_hint_y", None)
            kw.setdefault("height", dp(h) + 2 * mg() - dp(14))
        super().__init__(**kw)
        self._init_skin(kind)
        self.kind = kind
        self._color = color
        self._label = FaLabel(text, size=size, color=self._text_color(), align="center", wrap=False, auto_h=False,
                              size_hint=(1, 1), bold=(kind == "primary"))
        self.add_widget(self._label)
        self.bind(state=self._on_state, disabled=self._on_disabled)

    def _text_color(self):
        if self.kind == "primary":
            return "text_on_accent"
        if self._color:
            return self._color
        return "muted" if self.disabled else "text"

    def _on_state(self, *_):
        self.set_skin(pressed=(self.state == "down"))

    def _on_disabled(self, *_):
        self.set_skin(enabled=not self.disabled)
        self._label.set(self._label.ltext, "muted" if self.disabled and self.kind != "primary" else self._text_color())

    def set_text(self, text: str):
        self._label.set(text)

    def set_active(self, on: bool):
        """برای تب‌ها: روشن = فرورفته با متن نارنجی."""
        self.set_skin(kind="seg_on" if on else "seg")
        self._label.set(self._label.ltext, "accent" if on else "text")


class Tile(ButtonBehavior, SkinMixin, BoxLayout):
    """کاشی اصلی: دایره‌ی رنگی با نماد + عنوان + زیرعنوان."""

    def __init__(self, title: str, icon: str, accent: str, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(124))
        kw.setdefault("orientation", "vertical")
        kw.setdefault("padding", [mg() + dp(10)] * 4)
        kw.setdefault("spacing", dp(2))
        super().__init__(**kw)
        self._init_skin("tile")
        self.accent = accent
        self.icon = icon
        box = self
        top = BoxLayout(size_hint_y=None, height=dp(44))
        self._ic = Label(text=icon, font_name=FONT, font_size=sp(20), color=(1, 1, 1, 1), size_hint=(None, 1),
                         width=dp(44))
        with self._ic.canvas.before:
            self._ic_col = Color(*Theme.c(accent))
            self._ic_el = Ellipse()
        self._ic.bind(pos=self._ic_upd, size=self._ic_upd)
        top.add_widget(Label())                    # فاصله؛ نماد سمت راست (راست‌به‌چپ)
        top.add_widget(self._ic)
        box.add_widget(top)
        self.title = FaLabel(title, size=15, bold=True, auto_h=False, size_hint=(1, None), height=dp(26))
        self.sub = FaLabel("", size=12, color="muted", auto_h=False, wrap=False, size_hint=(1, None), height=dp(22))
        box.add_widget(self.title)
        box.add_widget(self.sub)
        self.bind(state=lambda *_: self.set_skin(pressed=(self.state == "down")))

    def _ic_upd(self, *_):
        d = min(self._ic.width, self._ic.height)
        self._ic_el.pos = (self._ic.center_x - d / 2, self._ic.center_y - d / 2)
        self._ic_el.size = (d, d)

    def set_sub(self, text: str, ok: bool = False):
        self.sub.set(text, "accent" if ok else "muted")


# ---------------------------------------------------------------- شمارنده‌ی ±
class Stepper(SkinMixin, BoxLayout):
    """[ − ]  مقدار  [ + ] روی زمینه‌ی فرورفته؛ با texts به‌صورت انتخاب از فهرست (مثل ماه‌ها)."""

    def __init__(self, minimum=0, maximum=100, value=0, step=1, suffix="", prefix="", texts=None, wrap=False,
                 on_change=None, on_wrap=None, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(64) + 2 * mg() - dp(14))
        kw.setdefault("padding", [mg() + dp(8), mg() + dp(4)])
        kw.setdefault("spacing", dp(6))
        super().__init__(**kw)
        self._init_skin("inset")
        self._min, self._max, self._step = minimum, maximum, step
        self._suffix, self._prefix, self._texts, self._wrap = suffix, prefix, texts, wrap
        if texts:
            self._min, self._max = 0, len(texts) - 1
        self._v = max(self._min, min(self._max, value))
        self.on_change, self.on_wrap = on_change, on_wrap
        self.plus = NeuButton("+", "round", size=20)
        self.minus = NeuButton("−", "round", size=20)
        self.plus.bind(on_release=lambda *_: self._move(+1))
        self.minus.bind(on_release=lambda *_: self._move(-1))
        self.label = FaLabel("", size=15, bold=True, align="center", wrap=False, auto_h=False)
        self.add_widget(self.plus)
        self.add_widget(self.label)
        self.add_widget(self.minus)
        self._refresh()

    @property
    def value(self) -> int:
        return self._v

    def set_value(self, v: int, notify=False):
        self._v = max(self._min, min(self._max, v))
        self._refresh()
        if notify and self.on_change:
            self.on_change(self._v)

    def _move(self, d: int):
        nv = self._v + d * self._step
        if nv > self._max:
            if self._wrap:
                nv = self._min
                if self.on_wrap:
                    self.on_wrap(+1)
            else:
                nv = self._max
        elif nv < self._min:
            if self._wrap:
                nv = self._max
                if self.on_wrap:
                    self.on_wrap(-1)
            else:
                nv = self._min
        if nv != self._v:
            self._v = nv
            self._refresh()
        if self.on_change:
            self.on_change(self._v)

    def _refresh(self):
        txt = self._texts[self._v] if self._texts else f"{self._prefix}{self._v}{self._suffix}"
        self.label.set(txt)


# ---------------------------------------------------------------- تب (قطعه‌های انتخاب‌پذیر)
class SegBar(BoxLayout):
    def __init__(self, labels: list[str], on_select, index: int = 0, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(56) + 2 * mg() - dp(14))
        kw.setdefault("spacing", dp(2))
        super().__init__(**kw)
        self.on_select = on_select
        self.buttons = []
        for i, t in enumerate(labels):
            b = NeuButton(t, "seg", size=14)
            b.bind(on_release=lambda _b, i=i: self.select(i, True))
            self.buttons.append(b)
        for b in reversed(self.buttons):          # راست‌به‌چپ: اولین برچسب در سمت راست
            self.add_widget(b)
        self.index = index
        self.select(index, False)

    def select(self, i: int, notify: bool):
        self.index = i
        for k, b in enumerate(self.buttons):
            b.set_active(k == i)
        if notify:
            self.on_select(i)


# ---------------------------------------------------------------- نوار پیشرفت
class Bar(Widget):
    value = NumericProperty(0)
    maximum = NumericProperty(1)

    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(12))
        super().__init__(**kw)
        with self.canvas:
            Color(*Theme.c("field"))
            self._track = RoundedRectangle()
            Color(*Theme.c("accent"))
            self._fill = RoundedRectangle()
        self.bind(pos=self._upd, size=self._upd, value=self._upd, maximum=self._upd)

    def _upd(self, *_):
        self._track.pos, self._track.size = self.pos, self.size
        self._track.radius = [self.height / 2]
        frac = 0 if self.maximum <= 0 else max(0.0, min(1.0, self.value / self.maximum))
        self._fill.pos = self.pos
        self._fill.size = (max(self.height, self.width * frac) if frac > 0 else 0, self.height)
        self._fill.radius = [self.height / 2]


# ---------------------------------------------------------------- تصویر مربعی و تصویر قابل‌لمس
class SquareImage(Image):
    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("fit_mode", "contain")
        super().__init__(**kw)
        self.opacity = 0                      # بدون بافت، Image مستطیل سفید می‌کشد
        self.bind(width=lambda w, v: setattr(w, "height", v))
        self.bind(texture=lambda w, t: setattr(w, "opacity", 1 if t is not None else 0))


class TouchImage(Image):
    """تصویری که نقطه‌ی لمس را بر حسب پیکسلِ تصویرِ اصلی گزارش می‌کند."""

    def __init__(self, on_tap, **kw):
        kw.setdefault("fit_mode", "contain")
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self.on_tap = on_tap
        self.img_size = (1, 1)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and touch.grab_current is None and abs(touch.dx) < 6 and abs(touch.dy) < 6:
            nw, nh = self.norm_image_size
            if nw > 0 and nh > 0:
                ox, oy = self.center_x - nw / 2, self.center_y - nh / 2
                fx, fy = (touch.x - ox) / nw, (touch.y - oy) / nh
                if 0 <= fx <= 1 and 0 <= fy <= 1:
                    self.on_tap(fx * self.img_size[0], (1 - fy) * self.img_size[1])
                    return True
        return super().on_touch_up(touch)
