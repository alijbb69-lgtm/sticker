"""Telegram Date Studio — نسخه‌ی اندروید (Kivy). تمام منطق در src/mobile/core.py است."""
from __future__ import annotations

import os
import sys
import textwrap
import threading
import traceback
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))     # اجرای مستقیم در ریپو (روی کامپیوتر)

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import LabelBase
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner, SpinnerOption

import platform_android as plat
from src.mobile.core import MONTHS, Project
from src.mobile.rtl import visual
from src.vector_text.fonts import bundled_font_dir

FONT_UI = os.path.join(bundled_font_dir(), "DejaVuSans.ttf")      # دارای فرم‌های نمایشیِ عربی/فارسی
LabelBase.register(name="UI", fn_regular=FONT_UI)
ORANGE = (1.0, 0.55, 0.15, 1)


class UIOption(SpinnerOption):
    font_name = "UI"          # گزینه‌های فارسیِ منوی بازشو هم با فونت دارای فرم‌های نمایشی


def fa(text: str, width: int = 34) -> str:
    """متن منطقیِ فارسی → متن قابل‌نمایش (شکل‌دهی + راست‌به‌چپ + شکستن خط)."""
    lines = []
    for ln in str(text).split("\n"):
        lines += textwrap.wrap(ln, width) or [""]
    return visual("\n".join(lines))


def lbl(text="", **kw) -> Label:
    kw.setdefault("font_name", "UI")
    kw.setdefault("halign", "right")
    kw.setdefault("size_hint_y", None)
    l = Label(text=fa(text) if kw.pop("shape", True) else text, **kw)
    l.bind(width=lambda w, _v: setattr(w, "text_size", (w.width, None)))
    l.bind(texture_size=lambda w, ts: setattr(w, "height", max(ts[1] + dp(8), dp(28))))
    return l


def btn(text, cb, primary=False, **kw) -> Button:
    b = Button(text=fa(text), font_name="UI", size_hint_y=None, height=dp(52),
               background_normal="", background_color=ORANGE if primary else (0.25, 0.25, 0.3, 1), **kw)
    b.bind(on_release=lambda *_: cb())
    return b


class DateStudio(App):
    title = "Telegram Date Studio"

    def build(self):
        plat.request_permissions()
        self.proj = Project()
        self.jy, self.jm = 1405, 8
        self.fonts = self._font_list()
        self.last_files: list[str] = []
        self._busy = False
        self._pv_token = 0
        self._zip_uri = None

        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        sv = ScrollView(do_scroll_x=False)
        self.col = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        self.col.bind(minimum_height=self.col.setter("height"))
        sv.add_widget(self.col)
        root.add_widget(sv)

        c = self.col
        c.add_widget(lbl("ساخت استیکر تاریخ", font_size=dp(22), bold=True))
        c.add_widget(btn("انتخاب قالب (PNG یا TGS)", self.pick_template, primary=True))
        self.status = lbl("هنوز قالبی انتخاب نشده است.", font_size=dp(14))
        c.add_widget(self.status)

        # ماه و سال
        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        self.sp_month = Spinner(text=fa(MONTHS[self.jm - 1]), values=[fa(m) for m in MONTHS], font_name="UI", option_cls=UIOption,
                                background_normal="", background_color=(0.25, 0.25, 0.3, 1))
        self.sp_month.bind(text=lambda *_: self._month_changed())
        self.b_year_dn = Button(text="−", size_hint_x=None, width=dp(52), on_release=lambda *_: self._year(-1))
        self.b_year_up = Button(text="+", size_hint_x=None, width=dp(52), on_release=lambda *_: self._year(+1))
        self.l_year = Label(text=str(self.jy), size_hint_x=None, width=dp(70))
        for w in (self.b_year_up, self.l_year, self.b_year_dn, self.sp_month):
            row.add_widget(w)
        c.add_widget(lbl("ماه و سال", font_size=dp(13)))
        c.add_widget(row)

        # فونت‌ها
        names = [Path(p).stem for p in self.fonts]
        c.add_widget(lbl("فونت (فارسی و انگلیسی)", font_size=dp(13)))
        self.sp_font = Spinner(text=names[0], values=names, size_hint_y=None, height=dp(48))
        self.sp_font.bind(text=lambda *_: self._font_changed())
        c.add_widget(self.sp_font)
        c.add_widget(lbl("فونت‌های بیشتر: فایل .ttf را در حافظه‌ی گوشی داخل TelegramDateStudio/fonts بگذارید و برنامه را دوباره باز کنید.",
                         font_size=dp(11)))

        # اندازه و کشیدگی
        self.l_size = lbl("اندازه‌ی نوشته‌ها: ۱۰۰٪", font_size=dp(13))
        c.add_widget(self.l_size)
        self.sl_size = Slider(min=50, max=150, value=100, step=5, size_hint_y=None, height=dp(40))
        self.sl_size.bind(value=lambda *_: self._size_changed())
        c.add_widget(self.sl_size)
        c.add_widget(lbl("کشیدگی حروف (شـنـبـه)", font_size=dp(13)))
        self.kash_vals = ["خودکار", "۰", "۱", "۲", "۳", "۴", "۵"]
        self.sp_kash = Spinner(text=fa("خودکار"), values=[fa(v) for v in self.kash_vals], font_name="UI", option_cls=UIOption,
                               size_hint_y=None, height=dp(48))
        self.sp_kash.bind(text=lambda *_: self._kash_changed())
        c.add_widget(self.sp_kash)

        # پیش‌نمایش
        self.preview = Image(size_hint_y=None, height=dp(340), fit_mode="contain")
        c.add_widget(self.preview)
        self.pv_info = lbl("", font_size=dp(12))
        c.add_widget(self.pv_info)

        # ساخت
        self.b_gen = btn("ساخت استیکرهای این ماه", self.start_batch, primary=True)
        c.add_widget(self.b_gen)
        self.bar = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(10))
        c.add_widget(self.bar)
        self.result = lbl("", font_size=dp(13))
        c.add_widget(self.result)
        self.b_share = btn("اشتراک‌گذاری ZIP", self.share)
        self.b_share.disabled = True
        c.add_widget(self.b_share)
        return root

    # ------------------------------------------------------------ کمکی
    def _font_list(self) -> list[str]:
        out = [os.path.join(bundled_font_dir(), "DejaVuSans-Bold.ttf")]
        out += sorted(str(p) for p in Path(bundled_font_dir()).glob("*.ttf") if str(p) not in out)
        d = plat.user_fonts_dir()
        try:
            out += sorted(str(p) for p in Path(d).glob("*.ttf")) + sorted(str(p) for p in Path(d).glob("*.otf"))
        except Exception:  # noqa: BLE001
            pass
        seen, res = set(), []
        for p in out:
            if p not in seen and os.path.exists(p):
                seen.add(p)
                res.append(p)
        return res

    def _ui(self, fn, *a):
        Clock.schedule_once(lambda _dt: fn(*a))

    def _error(self, e: Exception):
        traceback.print_exc()
        self.result.text = fa("✘ " + str(e))

    # ------------------------------------------------------------ قالب
    def pick_template(self):
        if not plat.pick_file(lambda p: self._ui(self.load_template, p) if p else None):
            self._fallback_picker()

    def _fallback_picker(self):
        start = "/storage/emulated/0" if plat.on_android() else str(Path.home())
        fc = FileChooserListView(path=start, filters=["*.png", "*.tgs"])
        pop = Popup(title="Template", content=fc, size_hint=(0.95, 0.9))
        fc.bind(on_submit=lambda _fc, sel, _t: (pop.dismiss(), self.load_template(sel[0])) if sel else None)
        pop.open()

    def load_template(self, path: str):
        self.status.text = fa("در حال تحلیل قالب …")
        def work():
            msg = self.proj.load(path)
            self._ui(self._loaded, msg)
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, msg: str):
        self.status.text = fa(msg)
        self.b_gen.disabled = not self.proj.ok
        self.refresh_preview()

    # ------------------------------------------------------------ تنظیمات
    def _month_changed(self):
        vals = list(self.sp_month.values)
        if self.sp_month.text in vals:
            self.jm = vals.index(self.sp_month.text) + 1
            self.refresh_preview()

    def _year(self, d):
        self.jy = max(1300, min(1700, self.jy + d))
        self.l_year.text = str(self.jy)
        self.refresh_preview()

    def _font_changed(self):
        names = [Path(p).stem for p in self.fonts]
        if self.sp_font.text in names:
            p = self.fonts[names.index(self.sp_font.text)]
            self.proj.fa_font = self.proj.en_font = p
            self.refresh_preview()

    def _size_changed(self):
        v = int(self.sl_size.value)
        self.proj.scale_pct = v
        self.l_size.text = fa(f"اندازه‌ی نوشته‌ها: {v}٪")
        self._debounce_preview()

    def _kash_changed(self):
        vals = list(self.sp_kash.values)
        i = vals.index(self.sp_kash.text) if self.sp_kash.text in vals else 0
        self.proj.kashida_override = None if i == 0 else i - 1
        self.refresh_preview()

    def _debounce_preview(self):
        Clock.unschedule(self._deb)
        Clock.schedule_once(self._deb, 0.3)

    def _deb(self, *_):
        self.refresh_preview()

    # ------------------------------------------------------------ پیش‌نمایش
    def refresh_preview(self):
        if not self.proj.ok:
            return
        self._pv_token += 1
        token = self._pv_token
        jy, jm = self.jy, self.jm
        def work():
            try:
                im, info = self.proj.preview(jy, jm, 1, 600)
                buf = BytesIO()
                im.convert("RGB").save(buf, "PNG")
                buf.seek(0)
                self._ui(self._show_preview, token, buf, info)
            except Exception as e:  # noqa: BLE001
                self._ui(self._error, e)
        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, token, buf, info):
        if token != self._pv_token:
            return
        self.preview.texture = CoreImage(buf, ext="png").texture
        self.pv_info.text = fa(info)

    # ------------------------------------------------------------ ساخت ماهانه
    def start_batch(self):
        if self._busy or not self.proj.ok:
            return
        self._busy = True
        self.b_gen.disabled = True
        self.b_share.disabled = True
        self.result.text = fa("در حال ساخت …")
        jy, jm = self.jy, self.jm
        def prog(i, n, _m):
            self._ui(lambda: (setattr(self.bar, "max", n), setattr(self.bar, "value", i)))
        def work():
            try:
                res = self.proj.generate(jy, jm, plat.work_dir(self.user_data_dir), prog)
                files = [os.path.join(res.out_dir, r.filename) for r in res.results if r.ok]
                zp = res.zip_path
                saved_uri, where = None, ""
                if zp:
                    for f in files:
                        try:
                            plat.save_to_downloads(f, f"TelegramDateStudio/{jy}-{jm:02d}")
                        except Exception:  # noqa: BLE001
                            pass
                    saved_uri, where = plat.save_to_downloads(zp)
                self._ui(self._batch_done, res, saved_uri, where)
            except Exception as e:  # noqa: BLE001
                self._ui(self._batch_failed, e)
        threading.Thread(target=work, daemon=True).start()

    def _batch_done(self, res, uri, where):
        self._busy = False
        self.b_gen.disabled = False
        self._zip_uri = uri
        total = len(res.results)
        txt = f"{res.ok_count} از {total} استیکر معتبر ساخته شد."
        if where:
            txt += f"\nذخیره شد در: {where}"
        if res.failed:
            txt += f"\n✘ {len(res.failed)} فایل نامعتبر بود: {res.failed[0].filename}"
        self.result.text = fa(txt)
        self.b_share.disabled = uri is None

    def _batch_failed(self, e):
        self._busy = False
        self.b_gen.disabled = False
        self._error(e)

    def share(self):
        try:
            if not plat.share_uri(self._zip_uri):
                self.result.text = fa("ارسال فقط روی اندروید ممکن است؛ فایل در پوشه‌ی Downloads است.")
        except Exception as e:  # noqa: BLE001
            self._error(e)


if __name__ == "__main__":
    DateStudio().run()
