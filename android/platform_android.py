"""کارهای مخصوص اندروید: انتخاب فایل با انتخابگر سیستمی (SAF) و کپی به حافظه‌ی خودِ برنامه (بدون نیاز به مجوز و بدون
«permission denied»)، ذخیره در Downloads با MediaStore، و اشتراک‌گذاری. خارج از اندروید جایگزین ساده دارند."""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path


def on_android() -> bool:
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_STORAGE" in os.environ


def sdk_int() -> int:
    if not on_android():
        return 99
    try:
        from jnius import autoclass  # type: ignore
        return int(autoclass("android.os.Build$VERSION").SDK_INT)
    except Exception:  # noqa: BLE001
        return 99


def request_permissions():
    """فقط اندروید ۹ و پایین‌تر برای ذخیره در Downloads مجوز می‌خواهد؛ از ۱۰ به بعد لازم نیست."""
    if not on_android() or sdk_int() >= 29:
        return
    try:
        from android.permissions import Permission, request_permissions as rp  # type: ignore
        rp([Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE])
    except Exception:  # noqa: BLE001
        pass


def work_dir(app_user_data_dir: str) -> str:
    d = os.path.join(app_user_data_dir if on_android() else str(Path.home() / "TelegramDateStudio_out"), "out")
    os.makedirs(d, exist_ok=True)
    return d


_REQ = 4711


def pick_document(on_done, dest_dir: str) -> bool:
    """انتخابگر سیستمی اندروید. فایلِ انتخاب‌شده در dest_dir کپی می‌شود و on_done(مسیر یا None, خطا یا "") صدا زده می‌شود
    (در یک رشته‌ی پس‌زمینه). اگر انتخابگر در دسترس نباشد False برمی‌گرداند."""
    if not on_android():
        return False
    try:
        from android import activity  # type: ignore
        from jnius import autoclass  # type: ignore
        Intent = autoclass("android.content.Intent")
        Activity = autoclass("org.kivy.android.PythonActivity").mActivity
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("*/*")

        def cb(request, result, data):
            if request != _REQ:
                return
            try:
                activity.unbind(on_activity_result=cb)
            except Exception:  # noqa: BLE001
                pass
            if result != -1 or data is None or data.getData() is None:
                on_done(None, "")
                return
            uri = data.getData()

            def copy():
                try:
                    res = Activity.getContentResolver()
                    name = _display_name(res, uri) or "file"
                    os.makedirs(dest_dir, exist_ok=True)
                    dst = os.path.join(dest_dir, _safe(name))
                    pfd = res.openFileDescriptor(uri, "r")
                    fd = pfd.detachFd()
                    with os.fdopen(fd, "rb") as src, open(dst, "wb") as out:
                        shutil.copyfileobj(src, out)
                    on_done(dst, "")
                except Exception as e:  # noqa: BLE001
                    on_done(None, str(e))
            threading.Thread(target=copy, daemon=True).start()

        activity.bind(on_activity_result=cb)
        Activity.startActivityForResult(intent, _REQ)
        return True
    except Exception:  # noqa: BLE001
        return False


def _display_name(res, uri) -> str:
    try:
        cur = res.query(uri, None, None, None, None)
        if cur is not None:
            try:
                idx = cur.getColumnIndex("_display_name")
                if idx >= 0 and cur.moveToFirst():
                    return cur.getString(idx)
            finally:
                cur.close()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "._- ") else "_" for c in name) or "file"


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
    if sdk_int() >= 29:
        ContentValues = autoclass("android.content.ContentValues")
        Downloads = autoclass("android.provider.MediaStore$Downloads")
        cv = ContentValues()
        cv.put("_display_name", name)
        cv.put("mime_type", mime)
        cv.put("relative_path", f"Download/{subdir}")
        res = Activity.getContentResolver()
        uri = res.insert(Downloads.EXTERNAL_CONTENT_URI, cv)
        pfd = res.openFileDescriptor(uri, "w")
        fd = pfd.detachFd()
        with open(path, "rb") as f, os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(f, out)
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
    Activity.startActivity(Intent.createChooser(it, "Share"))
    return True
