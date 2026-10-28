"""کارهای مخصوص اندروید (انتخاب فایل، ذخیره در Downloads با MediaStore، اشتراک‌گذاری). خارج از اندروید بی‌اثر/جایگزین است."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def on_android() -> bool:
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_STORAGE" in os.environ


def request_permissions():
    if not on_android():
        return
    try:
        from android.permissions import Permission, request_permissions as rp  # type: ignore
        rp([Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])
    except Exception:  # noqa: BLE001
        pass


def user_fonts_dir() -> str:
    """پوشه‌ای که کاربر فونت‌های .ttf خودش را در آن می‌گذارد (حافظه‌ی داخلی ← TelegramDateStudio/fonts)."""
    if on_android():
        base = "/storage/emulated/0"
    else:
        base = str(Path.home())
    d = os.path.join(base, "TelegramDateStudio", "fonts")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return d


def work_dir(app_user_data_dir: str) -> str:
    d = os.path.join(app_user_data_dir if on_android() else str(Path.home() / "TelegramDateStudio_out"), "out")
    os.makedirs(d, exist_ok=True)
    return d


def pick_file(on_pick, filters=("*.png", "*.tgs")):
    """انتخابگر فایل سیستم (plyer). on_pick(path|None). اگر نبود False برمی‌گرداند تا رابط انتخابگر خودش را نشان دهد."""
    try:
        from plyer import filechooser  # type: ignore
        filechooser.open_file(on_selection=lambda sel: on_pick(sel[0] if sel else None),
                              filters=[["Stickers", *filters]], multiple=False)
        return True
    except Exception:  # noqa: BLE001
        return False


def save_to_downloads(path: str, subdir: str = "TelegramDateStudio", mime: str | None = None):
    """فایل را در «Downloads/<subdir>» ذخیره می‌کند. برمی‌گرداند (uri یا مسیر، توضیحِ جای فایل)."""
    name = os.path.basename(path)
    mime = mime or ("application/zip" if name.endswith(".zip") else "image/png" if name.endswith(".png")
                    else "application/octet-stream")
    if not on_android():
        dst = Path.home() / "Downloads" / subdir
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dst / name)
        return str(dst / name), str(dst / name)
    from jnius import autoclass  # type: ignore
    Activity = autoclass("org.kivy.android.PythonActivity").mActivity
    sdk = autoclass("android.os.Build$VERSION").SDK_INT
    if sdk >= 29:
        ContentValues = autoclass("android.content.ContentValues")
        Downloads = autoclass("android.provider.MediaStore$Downloads")
        cv = ContentValues()
        cv.put("_display_name", name)
        cv.put("mime_type", mime)
        cv.put("relative_path", f"Download/{subdir}")
        res = Activity.getContentResolver()
        uri = res.insert(Downloads.EXTERNAL_CONTENT_URI, cv)
        out = res.openOutputStream(uri)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 16)
                if not chunk:
                    break
                out.write(bytearray(chunk))
        out.close()
        return uri, f"Download/{subdir}/{name}"
    Env = autoclass("android.os.Environment")
    d = os.path.join(Env.getExternalStoragePublicDirectory(Env.DIRECTORY_DOWNLOADS).getAbsolutePath(), subdir)
    os.makedirs(d, exist_ok=True)
    shutil.copy(path, os.path.join(d, name))
    return os.path.join(d, name), f"Download/{subdir}/{name}"


def share_uri(uri, mime="application/zip"):
    """منوی اشتراک‌گذاری اندروید (مثلاً فرستادن ZIP به تلگرام)."""
    if not on_android() or isinstance(uri, str):
        return False
    from jnius import autoclass, cast  # type: ignore
    Intent = autoclass("android.content.Intent")
    Activity = autoclass("org.kivy.android.PythonActivity").mActivity
    it = Intent(Intent.ACTION_SEND)
    it.setType(mime)
    it.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
    it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    Activity.startActivity(Intent.createChooser(it, "ارسال"))
    return True
