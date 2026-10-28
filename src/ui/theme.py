"""تم نیومورفیسم روشن و شب. رنگ‌ها در یک «پالت» جمع شده‌اند و ویجت‌های سفارشی (neu.py) هنگام رسم از آن می‌خوانند."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QFont, QPalette


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface_hi: str       # بخش روشن‌تر گرادیان سطح برجسته
    surface_lo: str
    light: tuple          # سایه‌ی روشن (RGBA)
    dark: tuple           # سایه‌ی تیره (RGBA)
    text: str
    muted: str
    accent: str           # نارنجی
    accent2: str          # مرجانی
    teal: str
    violet: str
    pink: str
    ok: str
    err: str
    field: str            # زمینه‌ی فرورفته (جستجو، لیست)


LIGHT = Palette("light", bg="#e7ecf2", surface_hi="#eff3f8", surface_lo="#dde4ec",
                light=(255, 255, 255, 235), dark=(163, 177, 198, 190),
                text="#3b475a", muted="#8793a5", accent="#ff9a3c", accent2="#ff5f45",
                teal="#2cc3b4", violet="#8b72f0", pink="#f0679b", ok="#1f9d78", err="#d9534f", field="#dfe6ee")
DARK = Palette("dark", bg="#262a33", surface_hi="#2c313b", surface_lo="#22262e",
               light=(58, 65, 80, 230), dark=(12, 14, 18, 230),
               text="#e7eaf0", muted="#8a93a5", accent="#ff9a3c", accent2="#ff5f45",
               teal="#34d1c1", violet="#9d87ff", pink="#ff7aa9", ok="#3ddc97", err="#ff7b72", field="#20242b")

P: Palette = LIGHT


class _Bus(QObject):
    changed = Signal()


bus = _Bus()


def _qss(p: Palette) -> str:
    return f"""
QMainWindow, QDialog {{ background: {p.bg}; }}
QWidget#root, QWidget#colHost, QWidget#page {{ background: {p.bg}; }}
QLabel {{ color: {p.text}; background: transparent; }}
QLabel#title {{ font-size: 19pt; font-weight: 600; }}
QLabel#subtitle, QLabel#muted {{ color: {p.muted}; }}
QLabel#heading {{ font-size: 13pt; font-weight: 600; }}
QLabel#ok {{ color: {p.ok}; }}
QLabel#err {{ color: {p.err}; }}
QLabel#stepperValue {{ font-size: 11pt; font-weight: 600; }}
QToolTip {{ color: {p.text}; background: {p.bg}; border: 1px solid {p.muted}; padding: 4px; }}
QLineEdit {{ color: {p.text}; background: {p.field}; border: none; border-radius: 18px; min-height: 36px; padding: 0 16px; }}
QListWidget {{ background: {p.field}; border: none; border-radius: 20px; padding: 8px; outline: none; }}
QScrollArea {{ background: transparent; border: none; }}
QProgressBar {{ background: {p.field}; border: none; border-radius: 5px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.accent2}); border-radius: 5px; }}
QSlider::groove:horizontal {{ height: 8px; background: {p.field}; border-radius: 4px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.accent2}); border-radius: 4px; }}
QSlider::handle:horizontal {{ background: {p.surface_hi}; border: 2px solid {p.accent}; width: 16px; height: 16px; margin: -6px 0; border-radius: 10px; }}
QScrollBar:vertical {{ background: {p.field}; width: 14px; margin: 6px 3px; border-radius: 7px; }}
QScrollBar::handle:vertical {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.accent2});
    border-radius: 5px; min-height: 44px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {p.accent2}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: {p.field}; height: 14px; margin: 3px 6px; border-radius: 7px; }}
QScrollBar::handle:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p.accent}, stop:1 {p.accent2});
    border-radius: 5px; min-width: 44px; margin: 2px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
"""


def _palette(p: Palette) -> QPalette:
    pal = QPalette()
    c = QColor
    pal.setColor(QPalette.Window, c(p.bg))
    pal.setColor(QPalette.WindowText, c(p.text))
    pal.setColor(QPalette.Base, c(p.field))
    pal.setColor(QPalette.AlternateBase, c(p.bg))
    pal.setColor(QPalette.Text, c(p.text))
    pal.setColor(QPalette.Button, c(p.bg))
    pal.setColor(QPalette.ButtonText, c(p.text))
    pal.setColor(QPalette.Highlight, c(p.accent))
    pal.setColor(QPalette.HighlightedText, c("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, c(p.muted))
    return pal


def set_mode(app, mode: str, save: bool = True) -> None:
    global P
    P = DARK if mode == "dark" else LIGHT
    app.setPalette(_palette(P))
    app.setStyleSheet(_qss(P))
    if save:
        QSettings("TelegramDateStudio", "App").setValue("theme", P.name)
    bus.changed.emit()


def saved_mode() -> str:
    v = QSettings("TelegramDateStudio", "App").value("theme", "light")
    return "dark" if v == "dark" else "light"


UI_FONT_NAMES = ["B Yekan", "B Yekan+", "BYekan", "Vazirmatn", "Segoe UI", "Tahoma"]


def _load_ui_fonts() -> list[str]:
    """فونت‌های رابط: هر فایل داخل assets/ui_fonts (مثلاً BYekan.ttf) یا فایل‌های *yekan* داخل assets/fonts."""
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase
    base = Path(__file__).resolve().parents[2] / "assets"
    files = [p for d in (base / "ui_fonts",) if d.is_dir() for p in d.iterdir() if p.suffix.lower() in (".ttf", ".otf")]
    fd = base / "fonts"
    if fd.is_dir():
        files += [p for p in fd.iterdir() if "yekan" in p.name.lower() and p.suffix.lower() in (".ttf", ".otf")]
    fams: list[str] = []
    for p in files:
        fid = QFontDatabase.addApplicationFont(str(p))
        if fid >= 0:
            fams += QFontDatabase.applicationFontFamilies(fid)
    return fams


def apply_theme(app, mode: str | None = None) -> None:
    app.setStyle("Fusion")
    f = QFont("Segoe UI", 10)
    f.setFamilies(_load_ui_fonts() + UI_FONT_NAMES)       # B Yekan اگر نصب یا کنار برنامه باشد، اول می‌آید
    app.setFont(f)
    set_mode(app, mode or saved_mode(), save=False)
