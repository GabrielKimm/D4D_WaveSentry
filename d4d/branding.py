"""WaveSentry's original outlined vectors, rendered at the display's native DPI."""
from PySide6.QtGui import QIcon
from PySide6.QtSvgWidgets import QSvgWidget

from .config import ROOT

PRODUCT_NAME = "WaveSentry"
WINDOW_TITLE = f"{PRODUCT_NAME} · RF Observatory"
BRAND_DIR = ROOT / "assets/branding"
SYMBOL = BRAND_DIR / "wavesentry-symbol-mint.svg"
WORDMARK = BRAND_DIR / "wavesentry-wordmark-offwhite.svg"


def app_icon():
    return QIcon(str(SYMBOL))


class BrandMark(QSvgWidget):
    def __init__(self, asset, width, parent=None):
        super().__init__(str(asset), parent)
        if not self.renderer().isValid():
            raise ValueError(f"Invalid WaveSentry brand asset: {asset}")
        size = self.renderer().defaultSize()
        self.setFixedSize(width, round(width * size.height() / size.width()))
        self.setStyleSheet("background: transparent;")
        self.setAccessibleName(PRODUCT_NAME)
        self.setToolTip("WaveSentry · RF 환경 관측 및 분석")
