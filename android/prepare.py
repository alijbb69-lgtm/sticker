"""قبل از ساخت APK: src و assets را کنار main.py کپی می‌کند (buildozer فقط همین پوشه را بسته‌بندی می‌کند).
fontTools به‌صورت «پایتون خالص» کپی می‌شود (فایل‌های .so ساخته‌شده برای x86 حذف می‌شوند؛ روی گوشی ARM کار نمی‌کنند)."""
import shutil
from pathlib import Path

here = Path(__file__).resolve().parent
root = here.parent
for name in ("src", "assets"):
    dst = here / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(root / name, dst, ignore=shutil.ignore_patterns("__pycache__", "ui", "*.pyc"))

import fontTools  # noqa: E402

ft = here / "fontTools"
if ft.exists():
    shutil.rmtree(ft)
shutil.copytree(Path(fontTools.__file__).parent, ft,
                ignore=shutil.ignore_patterns("__pycache__", "*.so", "*.pyd", "*.pyc", "*.c", "*.pxd", "*.pyx", "*.h"))
left = [p for p in ft.rglob("*") if p.suffix in (".so", ".pyd")]
assert not left, left
print("آماده‌ی buildozer.")
