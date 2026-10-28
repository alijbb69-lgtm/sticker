from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage, QPixmap


def pil_to_qimage(im: Image.Image) -> QImage:
    im = im.convert("RGBA")
    return QImage(im.tobytes("raw", "RGBA"), im.width, im.height, QImage.Format_RGBA8888).copy()


def pil_to_pixmap(im: Image.Image, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap.fromImage(pil_to_qimage(im))
    pm.setDevicePixelRatio(dpr)
    return pm
