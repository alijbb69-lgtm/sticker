"""قبل از ساخت APK: پوشه‌های src و assets ریپو را کنار main.py کپی می‌کند (buildozer فقط همین پوشه را بسته‌بندی می‌کند)."""
import shutil
from pathlib import Path

here = Path(__file__).resolve().parent
root = here.parent
for name in ("src", "assets"):
    dst = here / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(root / name, dst, ignore=shutil.ignore_patterns("__pycache__", "ui", "*.pyc", "ui_fonts"))
print("آماده‌ی buildozer.")
