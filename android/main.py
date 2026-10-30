"""Telegram Date Studio — نسخه‌ی اندروید (Kivy)، هم‌ظاهر با نسخه‌ی ویندوز: چهار کاشی، صفحه‌های درون‌پنجره‌ای، تم روشن/شب.
تمام منطق در src/mobile/core.py است؛ این فایل فقط رابط است."""
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))      # اجرای مستقیم در ریپو (کامپیوتر)

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

import platform_android as plat
from src.mobile.core import MONTHS, Project, load_state, save_state
from src.mobile.samples import EN_PROBE, FA_PROBE, SAMPLE_EN, SAMPLE_FA, missing_chars, sample_image
from src.png.session import annotated_image, blob_at
from src.calendars.jalali import day_info
from src.tgs.replacer import KASHIDA_SLOTS
from src.vector_text.fonts import bundled_font_dir

import ui_kit
from ui_kit import (Bar, FaLabel, NeuBox, NeuButton, SegBar, SquareImage, Stepper, Theme, Tile, TouchImage,
                    to_texture)
from src.mobile import neu_img


# ---------------------------------------------------------------- فونت رابط
def _has_forms(path: str) -> bool:
    """آیا فونت فرم‌های نمایشی عربی (برای شکل‌دهی دستی در Kivy) را دارد؟"""
    try:
        from fontTools.ttLib import TTFont
        cmap = TTFont(path, lazy=True).getBestCmap() or {}
        return all(c in cmap for c in (0xFEB3, 0xFEE3, 0xFE8D, 0xFEED))
    except Exception:  # noqa: BLE001
        return False


def pick_ui_font() -> tuple[str, str]:
    here = Path(__file__).resolve().parent
    for d in (here / "assets" / "ui_fonts", here.parent / "assets" / "ui_fonts"):
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in (".ttf", ".otf") and _has_forms(str(p)):
                    return str(p), str(p)
    b = bundled_font_dir()
    return os.path.join(b, "DejaVuSans.ttf"), os.path.join(b, "DejaVuSans-Bold.ttf")


_ui_gen = [0]


def apply_ui_font(path: str = "") -> str:
    """فونت رابط را (با نام تازه، تا کش متن‌ها قاطی نشود) ثبت می‌کند. فونت نامناسب → پیش‌فرض."""
    reg, bold = pick_ui_font()
    if path and os.path.exists(path) and _has_forms(path):
        reg = bold = path
        stem = os.path.splitext(path)
        b2 = stem[0] + "-Bold" + stem[1]
        if os.path.exists(b2):
            bold = b2
    _ui_gen[0] += 1
    name = f"UI{_ui_gen[0]}"
    LabelBase.register(name=name, fn_regular=reg, fn_bold=bold)
    ui_kit.FONT = name
    return reg


apply_ui_font()


class FontRow(ButtonBehavior, BoxLayout):
    """یک ردیف فهرست فونت: نام (بالا) + نمونه‌ی متن با همان فونت (پایین)."""

    def __init__(self, path: str, title: str, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(88))
        kw.setdefault("padding", [dp(14), dp(6)])
        super().__init__(**kw)
        self.path, self.selected = path, False
        with self.canvas.before:
            self._col = Color(0, 0, 0, 0)
            self._bg = RoundedRectangle(radius=[dp(16)])
        self.bind(pos=self._upd, size=self._upd)
        self.name_lbl = FaLabel(title, size=12, color="muted", auto_h=False, wrap=False, size_hint=(1, None),
                                height=dp(22))
        self.add_widget(self.name_lbl)
        self.holder = AnchorLayout(anchor_x="right", anchor_y="center")
        self.add_widget(self.holder)

    def _upd(self, *_):
        self._bg.pos, self._bg.size = self.pos, self.size

    def mark(self, on: bool):
        self.selected = on
        self._col.rgba = Theme.c("accent", 0.14) if on else (0, 0, 0, 0)
        self.name_lbl.set(self.name_lbl.ltext, "accent" if on else "muted")

    def set_sample(self, tex):
        self.holder.clear_widgets()
        self.holder.add_widget(Image(texture=tex, size_hint=(None, None), size=tex.size))


class Page(FloatLayout):
    """صفحه‌ی درون‌پنجره‌ای: نوار بالا با «بازگشت» و عنوان، محتوا، و دکمه‌ی «تأیید»."""

    def __init__(self, app, title: str, scroll: bool = False, **kw):
        super().__init__(**kw)
        self.app = app
        with self.canvas.before:
            Color(*Theme.c("bg"))
            self._bg = Rectangle()
        self.bind(pos=lambda *_: setattr(self._bg, "pos", self.pos), size=lambda *_: setattr(self._bg, "size", self.size))
        root = BoxLayout(orientation="vertical", padding=[dp(14), dp(14), dp(14), dp(10)], spacing=dp(10))
        top = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(8))
        top.add_widget(FaLabel(title, size=19, bold=True, auto_h=False))
        back = NeuButton("›", "round", size=26)
        back.bind(on_release=lambda *_: app.close_page())
        top.add_widget(back)
        root.add_widget(top)
        if scroll:
            sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
            self.inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10), padding=[0, 0, dp(4), dp(8)])
            self.inner.bind(minimum_height=self.inner.setter("height"))
            sv.add_widget(self.inner)
            root.add_widget(sv)
        else:
            self.inner = BoxLayout(orientation="vertical", spacing=dp(10))
            root.add_widget(self.inner)
        ok = NeuButton("تأیید", "primary", size=17)
        ok.bind(on_release=lambda *_: app.close_page())
        root.add_widget(ok)
        self.add_widget(root)
        self.on_close = None


class DateStudio(App):
    title = "Telegram Date Studio"

    # =========================================================== ساخت
    def build(self):
        if not plat.on_android():
            Window.size = (440, 860)
        plat.request_permissions()
        self.state_path = os.path.join(self.user_data_dir, "state.json")
        self.crash_path = os.path.join(self.user_data_dir, "crash.log")
        st = load_state(self.state_path)
        Theme.set("dark" if st.get("theme") == "dark" else "light")
        self.ui_font = st.get("ui_font", "")
        self.ui_scale = float(st.get("ui_scale", 1.0))
        apply_ui_font(self.ui_font)
        ui_kit.SCALE = self.ui_scale
        Window.clearcolor = Theme.c("bg")
        self.proj = Project()
        self.fonts_dir = os.path.join(self.user_data_dir, "fonts")
        self.tpl_dir = os.path.join(self.user_data_dir, "templates")
        self.fonts = self._font_list()
        self._scan_system_fonts()
        self.pages: list[Page] = []
        self._busy = False
        self._pv_running = self._pv_dirty = False
        self._last_pv = (None, "")
        self._zip_uri = None
        self._tpl_kind = "muted"
        self.frame = None
        self.root_fl = FloatLayout()
        self._build_main()
        self.root_fl.add_widget(self.main)
        Window.bind(on_keyboard=self._on_key)
        Clock.schedule_once(lambda _dt: self._restore_async(st), 0.3)
        return self.root_fl

    def _font_list(self) -> list[str]:
        """فونت‌های همراه برنامه (assets/fonts) + فونت‌های افزوده‌شده توسط کاربر + فونت‌های عربی/فارسی سیستم."""
        out = []
        here = Path(__file__).resolve().parent
        for d in (Path(bundled_font_dir()), here / "assets" / "fonts", here / "assets" / "ui_fonts", Path(self.fonts_dir)):
            if d.is_dir():
                out += sorted(str(p) for p in d.iterdir() if p.suffix.lower() in (".ttf", ".otf"))
        seen, res = set(), []
        for p in out:
            key = os.path.basename(p).lower()
            if key not in seen and os.path.exists(p):
                seen.add(key)
                res.append(p)
        return res

    def _scan_system_fonts(self):
        """فونت‌های سیستم اندروید که حروف فارسی دارند (در پس‌زمینه بررسی می‌شود)."""
        def work():
            try:
                from fontTools.ttLib import TTFont
            except Exception:  # noqa: BLE001
                return
            found = []
            for d in ("/system/fonts", "/system/font", "/product/fonts"):
                if not os.path.isdir(d):
                    continue
                for name in sorted(os.listdir(d)):
                    if not name.lower().endswith((".ttf", ".otf")):
                        continue
                    p = os.path.join(d, name)
                    try:
                        cm = TTFont(p, lazy=True).getBestCmap() or {}
                    except Exception:  # noqa: BLE001
                        continue
                    if 0x0628 in cm and 0x067E in cm:                  # ب و پ
                        found.append(p)
            def add():
                have = {os.path.basename(x).lower() for x in self.fonts}
                self.fonts += [p for p in found if os.path.basename(p).lower() not in have]
            self._ui(add)
        threading.Thread(target=work, daemon=True).start()

    # =========================================================== کمکی
    def _ui(self, fn, *a):
        Clock.schedule_once(lambda _dt: fn(*a))

    def _log(self, e: BaseException):
        try:
            with open(self.crash_path, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:  # noqa: BLE001
            pass
        traceback.print_exc()

    def err(self, e: BaseException):
        self._log(e)
        self.result.set("✘ " + str(e)[:300], "err")
        self._show_crash(e)

    def _show_crash(self, e: BaseException):
        """خطا را با جزئیات روی صفحه نشان می‌دهد (برای فرستادن به توسعه‌دهنده)."""
        from kivy.uix.label import Label
        mv = ModalView(size_hint=(0.94, 0.7))
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        txt = "".join(traceback.format_exception(type(e), e, e.__traceback__))[-1800:]
        lbl = Label(text=txt, font_name="Roboto", font_size=sp(10), halign="left", valign="top", size_hint_y=None)
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        lbl.bind(texture_size=lambda w, ts: setattr(w, "height", ts[1]))
        sv = ScrollView()
        sv.add_widget(lbl)
        box.add_widget(sv)
        b = NeuButton("بستن", "plain")
        b.bind(on_release=lambda *_: mv.dismiss())
        box.add_widget(b)
        mv.add_widget(box)
        mv.open()

    def save(self):
        save_state(self.proj, self.state_path, {"theme": Theme.pal.name, "ui_font": self.ui_font, "ui_scale": self.ui_scale})

    def _stem(self, p: str) -> str:
        return Path(p).stem

    # =========================================================== صفحه‌ی اصلی
    def _build_main(self):
        sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10), padding=[dp(14), dp(16), dp(14), dp(28)])
        col.bind(minimum_height=col.setter("height"))
        sv.add_widget(col)
        self.main = sv

        head = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(8))
        titles = BoxLayout(orientation="vertical")
        titles.add_widget(FaLabel("Telegram Date Studio", size=20, bold=True, auto_h=False, wrap=False))
        titles.add_widget(FaLabel("ساخت استیکر تاریخ برای یک ماه کامل", size=12, color="muted", auto_h=False, wrap=False))
        head.add_widget(titles)
        self.set_btn = NeuButton("⚙", "round", size=22)
        self.set_btn.bind(on_release=lambda *_: self.page_settings())
        head.add_widget(self.set_btn)
        self.mode_btn = NeuButton("☾" if Theme.pal.name == "light" else "☀", "round", size=22)
        self.mode_btn.bind(on_release=lambda *_: self.toggle_theme())
        head.add_widget(self.mode_btn)
        col.add_widget(head)

        grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(2), row_default_height=dp(124), row_force_default=True)
        grid.bind(minimum_height=grid.setter("height"))
        self.t_tpl = Tile("قالب", "▣", "accent")
        self.t_font = Tile("فونت‌ها", "A", "violet")
        self.t_month = Tile("ماه و سال", "▦", "teal")
        self.t_size = Tile("اندازه‌ها", "⇔", "pink")
        self.t_tpl.bind(on_release=lambda *_: self.page_template())
        self.t_font.bind(on_release=lambda *_: self.page_fonts())
        self.t_month.bind(on_release=lambda *_: self.page_month())
        self.t_size.bind(on_release=lambda *_: self.page_sizes())
        for t in (self.t_font, self.t_tpl, self.t_size, self.t_month):         # راست‌به‌چپ: قالب بالا-راست
            grid.add_widget(t)
        col.add_widget(grid)

        card = NeuBox("inset", pad=6)
        self.pv_img = SquareImage()
        card.add_widget(self.pv_img)
        col.add_widget(card)
        self.slider = Slider(min=0, max=1, value=0, size_hint_y=None, height=dp(40), value_track=True,
                             value_track_color=Theme.c("accent"), value_track_width=dp(4), cursor_size=(dp(26), dp(26)))
        self.slider.bind(value=self._on_slider)
        col.add_widget(self.slider)
        self.pv_info = FaLabel("", size=12, color="muted", align="center")
        col.add_widget(self.pv_info)

        self.fields_btn = NeuButton("تعیین نوشته‌ها روی استیکر ثابت", "plain", size=14)
        self.fields_btn.bind(on_release=lambda *_: self.page_png_fields())
        col.add_widget(self.fields_btn)
        self.gen_btn = NeuButton("ساخت استیکرهای این ماه", "primary", size=17)
        self.gen_btn.disabled = True
        self.gen_btn.bind(on_release=lambda *_: self.start_batch())
        col.add_widget(self.gen_btn)
        self.bar = Bar()
        col.add_widget(self.bar)
        self.result = FaLabel("", size=13, color="muted")
        col.add_widget(self.result)
        self.share_btn = NeuButton("اشتراک‌گذاری ZIP", "plain", size=14)
        self.share_btn.bind(on_release=lambda *_: self.share())
        col.add_widget(self.share_btn)
        self._toggle(self.fields_btn, False)
        self._toggle(self.share_btn, False)
        self._toggle(self.slider, False)
        self._refresh_tiles()

    @staticmethod
    def _toggle(w, on: bool):
        if not hasattr(w, "_h0"):
            w._h0 = w.height
        w.opacity = 1 if on else 0
        w.disabled = not on
        w.height = w._h0 if on else 0

    def _refresh_tiles(self):
        p = self.proj
        self.t_tpl.set_sub(p.name if p.ok else "انتخاب نشده", p.ok)
        self.t_font.set_sub(f"{self._stem(p.fa_font)} · {self._stem(p.en_font)}", True)
        self.t_month.set_sub(f"{MONTHS[p.jm - 1]} {p.jy}", True)
        n = len(p.slot_names())
        self.t_size.set_sub(f"{n} نوشته" if n else "پس از انتخاب قالب", bool(n))

    def toggle_theme(self):
        Theme.set("light" if Theme.pal.name == "dark" else "dark")
        self.rebuild_ui()

    def rebuild_ui(self):
        Window.clearcolor = Theme.c("bg")
        self.save()
        for pg in list(self.pages):
            self.root_fl.remove_widget(pg)
        self.pages.clear()
        self.root_fl.remove_widget(self.main)
        self._build_main()
        self.root_fl.add_widget(self.main)
        self._after_load_ui()
        im, info = self._last_pv
        if im is not None:
            self.pv_img.texture = im
            self.pv_info.set(info)

    # =========================================================== صفحه‌ها
    def open_page(self, pg: Page):
        self.pages.append(pg)
        self.root_fl.add_widget(pg)

    def close_page(self):
        if not self.pages:
            return
        pg = self.pages.pop()
        self.root_fl.remove_widget(pg)
        if pg.on_close:
            try:
                pg.on_close()
            except Exception as e:  # noqa: BLE001
                self._log(e)
        self._refresh_tiles()
        self.save()

    def _on_key(self, _win, key, *_a):
        if key == 27 and self.pages:                  # دکمه‌ی بازگشت اندروید
            self.close_page()
            return True
        return False

    # ---- قالب
    def page_template(self):
        pg = Page(self, "قالب استیکر", scroll=True)
        b = NeuButton("انتخاب فایل قالب (.png یا .tgs)", "plain")
        b.bind(on_release=lambda *_: self.pick_template())
        pg.inner.add_widget(b)
        self.tpl_status = FaLabel(self.proj.message, size=13, color=self._tpl_kind)
        pg.inner.add_widget(self.tpl_status)
        fb = NeuButton("تعیین نوشته‌ها روی استیکر ثابت", "plain", size=14)
        fb.bind(on_release=lambda *_: (self.close_page(), self.page_png_fields()))
        pg.inner.add_widget(fb)
        if self.proj.kind != "png":
            self._toggle(fb, False)
        self.open_page(pg)

    def pick_file(self, subdir: str, on_path):
        dest = os.path.join(self.user_data_dir, subdir)

        def done(path, err):
            self._ui(lambda: on_path(path, err))
        if plat.pick_document(done, dest):
            return
        if plat.on_android():
            on_path(None, "انتخابگر فایل در دسترس نیست")
            return
        start = str(Path.home())
        fc = FileChooserListView(path=start, filters=["*.png", "*.tgs", "*.ttf", "*.otf"])
        mv = ModalView(size_hint=(0.95, 0.9))
        mv.add_widget(fc)
        fc.bind(on_submit=lambda _f, sel, _t: (mv.dismiss(), on_path(sel[0], "")) if sel else None)
        mv.open()

    def pick_template(self):
        def got(path, err):
            if err:
                self._set_status("✘ " + err, "err")
            elif path:
                self.load_template(path, fresh=True)
        self.pick_file("templates", got)

    def _set_status(self, text: str, kind: str):
        self._tpl_kind = kind
        if getattr(self, "tpl_status", None) is not None:
            try:
                self.tpl_status.set(text, kind)
            except Exception:  # noqa: BLE001
                pass

    def load_template(self, path: str, fresh: bool = False, saved=None):
        self._set_status("در حال تحلیل قالب …", "muted")

        def work():
            try:
                if fresh:
                    self.proj.reset_adjustments()
                msg = self.proj.load(path, saved)
                self._ui(self._loaded, msg)
            except Exception as e:  # noqa: BLE001
                self._ui(self.err, e)
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, msg: str):
        kind = "err" if msg.startswith("✘") else "ok"
        self._set_status(msg, kind)
        self._after_load_ui()
        self.refresh_preview(0.05)
        self.save()

    def _after_load_ui(self):
        p = self.proj
        self.gen_btn.disabled = not p.ok
        self._toggle(self.fields_btn, p.ok and p.kind == "png")
        if p.ok and p.kind == "tgs":
            a, b = p.frame_range()
            self.slider.min, self.slider.max = a, max(b, a + 1)
            if self.frame is None:
                self.frame = (a + b) // 2
            self.slider.value = self.frame
            self._toggle(self.slider, True)
        else:
            self._toggle(self.slider, False)
        self._refresh_tiles()

    def _restore_async(self, st: dict):
        def work():
            try:
                self.proj.restore(st)
                self._ui(self._after_restore)
            except Exception as e:  # noqa: BLE001
                self._log(e)
        threading.Thread(target=work, daemon=True).start()

    def _after_restore(self):
        if self.proj.ok:
            self._set_status(self.proj.message, "ok")
            self._after_load_ui()
            self.refresh_preview(0.05)
        else:
            self._refresh_tiles()

    # ---- فونت‌ها
    def page_fonts(self):
        pg = Page(self, "فونت‌ها")
        proj = self.proj
        names = proj.slot_names()
        st = {"tab": 0, "slot": 0, "gen": 0, "rows": []}
        bar = SegBar(["شمسی", "میلادی", "هر متن جدا"], lambda i: (st.__setitem__("tab", i), fill()))
        pg.inner.add_widget(bar)
        slot_step = Stepper(texts=names or ["—"], wrap=True, on_change=lambda v: (st.__setitem__("slot", v), fill()))
        slot_step._h0 = slot_step.height
        pg.inner.add_widget(slot_step)
        self._toggle(slot_step, False)
        sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(4), padding=[dp(2), dp(2)])
        grid.bind(minimum_height=grid.setter("height"))
        sv.add_widget(grid)
        pg.inner.add_widget(sv)
        warn = FaLabel(" ", size=12, color="err")
        pg.inner.add_widget(warn)
        add = NeuButton("افزودن فونت از حافظه‌ی گوشی …", "plain", size=14)
        pg.inner.add_widget(add)

        def current_path() -> str:
            if st["tab"] == 0:
                return proj.fa_font
            if st["tab"] == 1:
                return proj.en_font
            return proj.slot_fonts.get(names[st["slot"]], "") if names else ""

        def set_warn():
            p = current_path()
            if not p:
                warn.set(" ")
                return
            probe, label = (EN_PROBE, "انگلیسی") if st["tab"] == 1 else (FA_PROBE, "فارسی")

            def work():
                miss = missing_chars(p, probe)
                txt = (f"⚠ این فونت بعضی حروف {label} را ندارد: " + " ".join(miss[:10])) if miss else " "
                self._ui(lambda: warn.set(txt))
            threading.Thread(target=work, daemon=True).start()

        def mark():
            cur = current_path()
            for r in st["rows"]:
                r.mark(r.path == cur)

        def picked(row: FontRow):
            p = row.path
            if st["tab"] == 0:
                proj.fa_font = p
            elif st["tab"] == 1:
                proj.en_font = p
            elif names:
                if p:
                    proj.slot_fonts[names[st["slot"]]] = p
                else:
                    proj.slot_fonts.pop(names[st["slot"]], None)
            mark()
            set_warn()
            self.refresh_preview(0.2)

        def fill():
            st["gen"] += 1
            gen = st["gen"]
            self._toggle(slot_step, st["tab"] == 2 and bool(names))
            grid.clear_widgets()
            st["rows"] = []
            items = ([("", "طبق تنظیم کلی")] if st["tab"] == 2 else []) + [(p, self._stem(p)) for p in self.fonts]
            sample = SAMPLE_EN if st["tab"] == 1 else SAMPLE_FA
            color = tuple(int(v * 255) for v in Theme.c("text")[:3])
            hpx = int(sp(18))
            for p, title in items:
                r = FontRow(p, title)
                r.bind(on_release=lambda row: picked(row))
                grid.add_widget(r)
                st["rows"].append(r)
            mark()
            set_warn()

            def work():
                for r in list(st["rows"]):
                    if gen != st["gen"] or not r.path:
                        continue
                    try:
                        im = sample_image(r.path, sample, color, hpx, int(Window.width * 0.8))
                    except Exception:  # noqa: BLE001
                        continue
                    # ساخت بافت OpenGL فقط در رشته‌ی اصلی (در رشته‌ی دیگر مستطیل سیاه می‌شود)
                    self._ui(lambda r=r, im=im: r.set_sample(to_texture(im)) if gen == st["gen"] else None)
            threading.Thread(target=work, daemon=True).start()

        def add_font(*_):
            def got(path, err):
                if err or not path:
                    warn.set("✘ " + (err or "فایلی انتخاب نشد"), "err")
                    return
                if not path.lower().endswith((".ttf", ".otf")):
                    warn.set("✘ فقط فایل .ttf یا .otf", "err")
                    return
                if path not in self.fonts:
                    self.fonts.append(path)
                fill()
            self.pick_file("fonts", got)
        add.bind(on_release=add_font)
        fill()
        self.open_page(pg)

    # ---- تنظیمات برنامه
    def page_settings(self):
        pg = Page(self, "تنظیمات برنامه", scroll=True)
        old = (self.ui_font, self.ui_scale, Theme.pal.name)
        st = {"font": self.ui_font, "scale": self.ui_scale, "mode": Theme.pal.name}
        inner = pg.inner

        inner.add_widget(FaLabel("حالت نمایش", size=13, color="muted"))
        inner.add_widget(SegBar(["شب", "روشن"], lambda i: st.__setitem__("mode", "dark" if i == 0 else "light"),
                                index=0 if st["mode"] == "dark" else 1))
        inner.add_widget(FaLabel("اندازه‌ی نوشته‌های برنامه", size=13, color="muted"))
        scales = [0.85, 1.0, 1.2, 1.4]
        cur = min(range(4), key=lambda i: abs(scales[i] - st["scale"]))
        inner.add_widget(SegBar(["کوچک", "معمولی", "بزرگ", "خیلی بزرگ"],
                                lambda i: st.__setitem__("scale", scales[i]), index=cur))
        inner.add_widget(FaLabel("فونت برنامه (فقط فونت‌هایی که حروف فارسی را درست نشان می‌دهند):", size=13, color="muted"))
        warn = FaLabel(" ", size=12, color="muted")
        rows: list[FontRow] = []
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        box.bind(minimum_height=box.setter("height"))
        inner.add_widget(box)
        inner.add_widget(warn)

        def mark():
            for r in rows:
                r.mark(r.path == st["font"])

        def pick(row):
            st["font"] = row.path
            mark()
            warn.set("با «تأیید» اعمال می‌شود.", "muted")

        def build_rows(paths):
            box.clear_widgets()
            rows.clear()
            for p, t in [("", "پیش‌فرض برنامه")] + [(q, self._stem(q)) for q in paths]:
                r = FontRow(p, t)
                r.bind(on_release=pick)
                box.add_widget(r)
                rows.append(r)
            mark()
            color = tuple(int(v * 255) for v in Theme.c("text")[:3])

            def work():
                for r in list(rows):
                    if not r.path:
                        continue
                    try:
                        im = sample_image(r.path, SAMPLE_FA, color, int(sp(18)), int(Window.width * 0.8))
                    except Exception:  # noqa: BLE001
                        continue
                    self._ui(lambda r=r, im=im: r.set_sample(to_texture(im)))
            threading.Thread(target=work, daemon=True).start()

        def scan():
            ok = [p for p in self.fonts if _has_forms(p)]
            self._ui(build_rows, ok)
        threading.Thread(target=scan, daemon=True).start()

        add = NeuButton("افزودن فونت از حافظه‌ی گوشی …", "plain", size=14)

        def add_font(*_):
            def got(path, err):
                if err or not path:
                    warn.set("✘ " + (err or "فایلی انتخاب نشد"), "err")
                    return
                if not path.lower().endswith((".ttf", ".otf")):
                    warn.set("✘ فقط فایل .ttf یا .otf", "err")
                    return
                if path not in self.fonts:
                    self.fonts.append(path)
                if _has_forms(path):
                    build_rows([p for p in self.fonts if _has_forms(p)])
                else:
                    warn.set("این فونت برای نوشته‌های برنامه مناسب نیست (شکل‌های حروف عربی را ندارد)؛ برای استیکر قابل استفاده است.", "err")
            self.pick_file("fonts", got)
        add.bind(on_release=add_font)
        inner.add_widget(add)

        inner.add_widget(FaLabel("ابزارها", size=13, color="muted"))
        reset = NeuButton("بازنشانی تنظیمات فونت/اندازه/جابه‌جایی", "plain", size=14)
        reset.bind(on_release=lambda *_: (self.proj.reset_adjustments(), self.refresh_preview(0.1),
                                          warn.set("بازنشانی شد.", "ok")))
        inner.add_widget(reset)
        logb = NeuButton("نمایش گزارش خطاهای برنامه", "plain", size=14)

        def show_log(*_):
            try:
                txt = open(self.crash_path, encoding="utf-8").read()[-2500:] or "گزارشی ثبت نشده."
            except Exception:  # noqa: BLE001
                txt = "گزارشی ثبت نشده."
            self._show_text(txt)
        logb.bind(on_release=show_log)
        inner.add_widget(logb)
        inner.add_widget(FaLabel("Telegram Date Studio — نسخه‌ی اندروید ۰٫۲", size=12, color="muted", align="center"))

        def closing():
            if (st["font"], st["scale"], st["mode"]) == old:
                return
            self.ui_font, self.ui_scale = st["font"], st["scale"]
            Theme.set(st["mode"])
            apply_ui_font(self.ui_font)
            ui_kit.SCALE = self.ui_scale
            self.rebuild_ui()
        pg.on_close = closing
        self.open_page(pg)

    def _show_text(self, txt: str):
        from kivy.uix.label import Label
        mv = ModalView(size_hint=(0.94, 0.7))
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        lbl = Label(text=txt, font_name="Roboto", font_size=sp(10), halign="left", valign="top", size_hint_y=None)
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        lbl.bind(texture_size=lambda w, ts: setattr(w, "height", ts[1]))
        sv = ScrollView()
        sv.add_widget(lbl)
        box.add_widget(sv)
        b = NeuButton("بستن", "plain")
        b.bind(on_release=lambda *_: mv.dismiss())
        box.add_widget(b)
        mv.add_widget(box)
        mv.open()

    # ---- ماه و سال
    def page_month(self):
        pg = Page(self, "ماه و سال", scroll=True)
        proj = self.proj
        info = FaLabel("", size=13, color="muted")

        def upd(*_):
            proj.jm, proj.jy = month.value + 1, year.value
            d1 = day_info(proj.jy, proj.jm, 1)
            info.set(f"۱ {d1.jalali_month_fa} = {d1.date.day} {d1.gregorian_month_en.capitalize()} {d1.date.year}")
            self.refresh_preview(0.2)
        month = Stepper(texts=MONTHS, value=proj.jm - 1, wrap=True, on_change=upd,
                        on_wrap=lambda d: year.set_value(year.value + d))
        year = Stepper(1300, 1700, proj.jy, on_change=upd)
        pg.inner.add_widget(FaLabel("ماه", size=13, color="muted"))
        pg.inner.add_widget(month)
        pg.inner.add_widget(FaLabel("سال", size=13, color="muted"))
        pg.inner.add_widget(year)
        pg.inner.add_widget(info)
        upd()
        self.open_page(pg)

    # ---- اندازه‌ها / جابه‌جایی / کشیدگی
    def page_sizes(self):
        pg = Page(self, "اندازه و جای نوشته‌ها", scroll=True)
        proj = self.proj
        names = proj.slot_names()
        if not names:
            pg.inner.add_widget(FaLabel("ابتدا یک قالب انتخاب کنید.", size=14, color="muted"))
            self.open_page(pg)
            return
        kash_names = [n for n in names if n in KASHIDA_SLOTS]
        labels = ["اندازه", "جابه‌جایی"] + (["کشیدگی"] if kash_names else [])
        body = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        body.bind(minimum_height=body.setter("height"))
        hint = FaLabel("", size=12, color="muted")
        steppers: dict = {}

        def changed():
            self.refresh_preview(0.25)

        def show(i: int):
            body.clear_widgets()
            steppers.clear()
            if i == 0:
                hint.set("درصد اندازه‌ی هر متن نسبت به نوشته‌ی اصلی قالب.")
                for n in names:
                    body.add_widget(FaLabel(n, size=13, color="muted"))
                    s = Stepper(30, 300, proj.sizes.get(n, 100), step=5, suffix="٪",
                                on_change=lambda v, n=n: (proj.sizes.__setitem__(n, v), changed()))
                    body.add_widget(s)
            elif i == 1:
                hint.set("↔ مثبت = به راست، ↕ مثبت = به پایین (پیکسل).")
                for n in names:
                    body.add_widget(FaLabel(n, size=13, color="muted"))
                    x0, y0 = proj.offsets.get(n, (0, 0))
                    row = BoxLayout(size_hint_y=None, height=dp(78), spacing=dp(4))
                    sx = Stepper(-120, 120, x0, step=2, prefix="↔ ")
                    sy = Stepper(-120, 120, y0, step=2, prefix="↕ ")
                    steppers[n] = (sx, sy)

                    def cb(_v, n=n):
                        a, b = steppers[n]
                        proj.offsets[n] = (a.value, b.value)
                        changed()
                    sx.on_change = sy.on_change = cb
                    row.add_widget(sy)
                    row.add_widget(sx)
                    body.add_widget(row)
            else:
                hint.set("کشیدگی حروف: ۰ = ساده، ۳ = شـــنـــبـــه. به‌طور خودکار از روی قالب حدس زده می‌شود.")
                for n in kash_names:
                    body.add_widget(FaLabel(n, size=13, color="muted"))
                    s = Stepper(0, 6, proj.kashida_of(n),
                                on_change=lambda v, n=n: (proj.kash_user.__setitem__(n, v), changed()))
                    body.add_widget(s)

        pg.inner.add_widget(SegBar(labels, show))
        pg.inner.add_widget(hint)
        pg.inner.add_widget(body)
        reset = NeuButton("بازگشت به حالت اصلی", "plain", size=14)

        def do_reset(*_):
            proj.reset_adjustments()
            show(0)
            changed()
        reset.bind(on_release=do_reset)
        pg.inner.add_widget(reset)
        show(0)
        self.open_page(pg)

    # ---- نواحی استیکر ثابت
    def page_png_fields(self):
        proj = self.proj
        if proj.kind != "png" or not proj.png:
            return
        pg = Page(self, "نوشته‌ها روی استیکر", scroll=True)
        names = proj.all_slot_names()
        st = {"assign": dict(proj.png_assign()), "ymd": list(proj.png_base()), "slot": 0}
        info = FaLabel("", size=12, color="muted")
        img = TouchImage(on_tap=lambda x, y: tap(x, y))
        W, H = proj.png.img.size
        img.img_size = (W, H)
        img.bind(width=lambda w, v: setattr(w, "height", v * H / max(W, 1)))
        digit_btn = NeuButton("", "plain", size=13)

        def commit():
            try:
                proj.png_set(st["assign"], tuple(st["ymd"]))
            except Exception:  # noqa: BLE001
                return                           # تاریخِ نامعتبر (مثل ۳۱ اسفند)
            self.refresh_preview(0.3)

        def redraw():
            cur = names[st["slot"]]
            im = annotated_image(proj.png.img, proj.png.blobs, st["assign"], names, cur, 900)
            img.texture = to_texture(im)
            a = st["assign"].get(cur)
            if a:
                info.set(f"«{cur}» ← ناحیه‌ی {a[0].split('/')[-1]}")
                digit_btn.set_text("ارقام: فارسی" if a[1] == "persian" else "ارقام: لاتین")
            else:
                info.set(f"«{cur}» هنوز ناحیه‌ای ندارد (اگر در این استیکر نیست، خالی بگذارید).")
                digit_btn.set_text("ارقام: —")

        def tap(ix, iy):
            b = blob_at(proj.png.blobs, ix, iy)
            if b is None:
                return
            cur = names[st["slot"]]
            for k in [k for k, v in st["assign"].items() if v[0] == b.id and k != cur]:
                del st["assign"][k]
            st["assign"][cur] = (b.id, st["assign"].get(cur, (None, "keep"))[1])
            redraw()
            commit()

        def toggle_digits(*_):
            cur = names[st["slot"]]
            if cur in st["assign"]:
                bid, dg = st["assign"][cur]
                st["assign"][cur] = (bid, "latin" if dg == "persian" else "persian")
                redraw()
                commit()

        def clear(*_):
            st["assign"].pop(names[st["slot"]], None)
            redraw()
            commit()

        def auto(*_):
            st["assign"] = {k: tuple(v) for k, v in proj.png_suggest(tuple(st["ymd"])).items()}
            redraw()
            commit()

        def date_changed(_v):
            st["ymd"] = [year.value, month.value + 1, day.value]
            commit()

        pg.inner.add_widget(FaLabel("۱) تاریخی را که الان روی این استیکر نوشته شده وارد کنید:", size=13, color="muted"))
        day = Stepper(1, 31, st["ymd"][2], suffix=" روز", on_change=date_changed)
        month = Stepper(texts=MONTHS, value=st["ymd"][1] - 1, wrap=True, on_change=date_changed)
        year = Stepper(1300, 1700, st["ymd"][0], on_change=date_changed)
        for w in (day, month, year):
            pg.inner.add_widget(w)
        pg.inner.add_widget(FaLabel("۲) یک متغیر را انتخاب کنید و روی نوشته‌ی مربوط در تصویر بزنید:", size=13, color="muted"))
        slot = Stepper(texts=names, wrap=True, on_change=lambda v: (st.__setitem__("slot", v), redraw()))
        pg.inner.add_widget(slot)
        pg.inner.add_widget(img)
        row = BoxLayout(size_hint_y=None, height=dp(78), spacing=dp(4))
        cb = NeuButton("حذف این ناحیه", "plain", size=13)
        cb.bind(on_release=clear)
        digit_btn.bind(on_release=toggle_digits)
        row.add_widget(cb)
        row.add_widget(digit_btn)
        pg.inner.add_widget(row)
        ab = NeuButton("پیشنهاد خودکار", "plain", size=14)
        ab.bind(on_release=auto)
        pg.inner.add_widget(ab)
        pg.inner.add_widget(info)
        redraw()
        pg.on_close = lambda: self._set_status(proj.message, "ok")
        self.open_page(pg)

    # =========================================================== پیش‌نمایش
    def _on_slider(self, _w, v):
        if self.proj.ok and self.proj.kind == "tgs":
            self.frame = int(v)
            self.refresh_preview(0.12)

    def refresh_preview(self, delay: float = 0.25):
        Clock.unschedule(self._do_preview)
        Clock.schedule_once(self._do_preview, delay)

    def _do_preview(self, *_):
        if not self.proj.ok or self._busy:
            return
        if self._pv_running:
            self._pv_dirty = True
            return
        self._pv_running = True
        self._pv_dirty = False
        jy, jm, fr = self.proj.jy, self.proj.jm, self.frame

        def work():
            try:
                im, info = self.proj.preview(jy, jm, 1, 600, fr)
                self._ui(self._show_preview, im, info)
            except Exception as e:  # noqa: BLE001
                self._log(e)
                self._ui(lambda: self.pv_info.set("⚠ " + str(e)[:200], "err"))
            finally:
                self._pv_running = False
                if self._pv_dirty:
                    self._ui(self.refresh_preview, 0.05)
        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, im, info: str):
        tex = to_texture(im)                       # فقط در رشته‌ی اصلی
        self._last_pv = (tex, info)
        self.pv_img.texture = tex
        self.pv_info.set(info)

    # =========================================================== ساخت ماهانه
    def start_batch(self):
        if self._busy or not self.proj.ok:
            return
        self._busy = True
        self.gen_btn.disabled = True
        self._toggle(self.share_btn, False)
        self.result.set("در حال ساخت …", "muted")
        self.bar.value = 0
        jy, jm = self.proj.jy, self.proj.jm

        def prog(i, n, _m):
            self._ui(lambda: (setattr(self.bar, "maximum", n), setattr(self.bar, "value", i)))

        def work():
            try:
                res = self.proj.generate(jy, jm, plat.work_dir(self.user_data_dir), prog)
                uri, where = None, ""
                if res.zip_path:
                    sub = f"TelegramDateStudio/{jy}-{jm:02d}"
                    for r in res.results:
                        if r.ok:
                            try:
                                plat.save_to_downloads(os.path.join(res.out_dir, r.filename), sub)
                            except Exception as e:  # noqa: BLE001
                                self._log(e)
                    uri, where = plat.save_to_downloads(res.zip_path, sub)
                self._ui(self._batch_done, res, uri, where)
            except Exception as e:  # noqa: BLE001
                self._ui(self._batch_failed, e)
        threading.Thread(target=work, daemon=True).start()

    def _batch_done(self, res, uri, where):
        self._busy = False
        self.gen_btn.disabled = False
        self._zip_uri = uri
        txt = f"{res.ok_count} از {len(res.results)} استیکر معتبر ساخته شد."
        if where:
            txt += f"\nذخیره شد در: {where}"
        if res.failed:
            txt += f"\n✘ {len(res.failed)} فایل نامعتبر بود: {res.failed[0].filename} — {'; '.join(res.failed[0].messages)[:100]}"
        self.result.set(txt, "err" if res.failed else "ok")
        self._toggle(self.share_btn, uri is not None)
        self.refresh_preview(0.1)

    def _batch_failed(self, e):
        self._busy = False
        self.gen_btn.disabled = False
        self.err(e)

    def share(self):
        try:
            if not plat.share_uri(self._zip_uri):
                self.result.set("اشتراک‌گذاری فقط روی اندروید ممکن است؛ فایل‌ها در پوشه‌ی Downloads هستند.", "muted")
        except Exception as e:  # noqa: BLE001
            self.err(e)

    def on_stop(self):
        self.save()


if __name__ == "__main__":
    DateStudio().run()
