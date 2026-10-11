"""Custom-painted scientific views. No synthetic live data."""
from collections import deque
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont, QImage, QLinearGradient
from PySide6.QtWidgets import QWidget

TEAL = QColor("#99c4b3")
MUTED = QColor("#9b9fa7")
GRID = QColor("#33363c")
COLORS = {"drone": "#ff966a", "wifi": "#99c4b3", "bt": "#839dfa"}


def font(size=10, mono=False):
    return QFont("Consolas" if mono else "Segoe UI", size)


class Spectrum(QWidget):
    def __init__(self):
        super().__init__()
        self.values = None
        self.peak = None
        self.replay = False
        self.survey = False
        self.center_mhz = 2449.5
        self.setMinimumHeight(168)

    def clear(self):
        self.values = self.peak = None
        self.update()

    def set_data(self, values):
        if values is not None:
            self.values = values
            self.peak = values.copy() if self.peak is None else np.maximum(values, self.peak - 0.3)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(46, 22, self.width() - 64, self.height() - 51)
        p.fillRect(rect, QColor("#191b1e"))
        target = QRectF(rect.left() + rect.width() * 0.25, rect.top(), rect.width() * 0.5, rect.height())
        if not self.survey:
            p.fillRect(target, QColor("#23312d"))
        p.setFont(font(8, True))
        for value in range(-60, 1, 15):
            y = rect.bottom() - (value + 65) / 70 * rect.height()
            p.setPen(GRID)
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.setPen(MUTED)
            p.drawText(QRectF(0, y - 8, 37, 18), Qt.AlignRight, str(value))
        for i in range(5):
            x = rect.left() + rect.width() * i / 4
            p.setPen(GRID)
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            p.setPen(TEAL if i in (1, 3) else MUTED)
            p.drawText(QRectF(x - 33, rect.bottom() + 8, 66, 20), Qt.AlignCenter, f"{self.center_mhz - 10 + i * 5:.1f}")
        p.setPen(TEAL)
        p.drawText(QRectF(target.left() + 10, 0, target.width(), 20), "LAST IQ · 20 MHz" if self.survey else "TARGET WINDOW · 10 MHz")
        p.setPen(MUTED)
        p.drawText(QRectF(0, 0, 44, 20), "rel. dB")
        if self.values is None:
            p.setPen(MUTED)
            p.setFont(font(10))
            p.drawText(rect, Qt.AlignCenter, "녹화 이미지 재생 · RF 스펙트럼 없음" if self.replay else "수신을 시작하면 주파수 스펙트럼이 표시됩니다")
            return
        p.setClipRect(rect)
        for values, color, fill in ((self.peak, QColor("#526a62"), False), (self.values, TEAL, True)):
            path = QPainterPath()
            for i, value in enumerate(values):
                point = QPointF(rect.left() + i / (len(values) - 1) * rect.width(),
                                rect.bottom() - min(1, max(0, (float(value) + 65) / 70)) * rect.height())
                if i == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            if fill:
                area = QPainterPath(path)
                area.lineTo(rect.bottomRight())
                area.lineTo(rect.bottomLeft())
                area.closeSubpath()
                gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                gradient.setColorAt(0, QColor(105, 221, 196, 65))
                gradient.setColorAt(1, QColor(105, 221, 196, 0))
                p.fillPath(area, gradient)
            p.setPen(QPen(color, 1.3 if fill else 0.8))
            p.drawPath(path)


class Waterfall(QWidget):
    def __init__(self):
        super().__init__()
        self.rows = deque(maxlen=180)
        self.setMinimumHeight(155)
        points = np.array([[8, 16, 23], [17, 44, 55], [30, 99, 104], [94, 195, 164], [222, 238, 146]])
        self.lut = np.column_stack([np.interp(np.arange(256), np.linspace(0, 255, 5), points[:, c]) for c in range(3)]).astype(np.uint8)

    def clear(self):
        self.rows.clear()
        self.update()

    def set_data(self, values):
        if values is not None:
            self.rows.appendleft(values)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        r = QRectF(46, 4, self.width() - 64, self.height() - 24)
        p.fillRect(r, QColor("#191b1e"))
        if self.rows:
            array = np.full((180, 512), -65, dtype=np.float32)
            array[:len(self.rows)] = np.stack(self.rows)
            rgb = np.ascontiguousarray(self.lut[np.clip((array + 65) / 65 * 255, 0, 255).astype(np.uint8)])
            image = QImage(rgb.data, 512, 180, rgb.strides[0], QImage.Format_RGB888)
            p.drawImage(r, image)
        else:
            p.setFont(font(10))
            p.setPen(MUTED)
            p.drawText(r, Qt.AlignCenter, "수신 데이터 대기")
        p.setPen(QPen(QColor(105, 221, 196, 120), 1, Qt.DashLine))
        for fraction in (0.25, 0.75):
            x = r.left() + r.width() * fraction
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.setFont(font(8, True))
        p.setPen(MUTED)
        p.drawText(QRectF(0, r.top(), 38, 20), Qt.AlignRight, "NOW")
        p.drawText(QRectF(0, r.bottom() - 18, 38, 20), Qt.AlignRight, "-180f")
        p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 20), "2439.5                 DISPLAYED FRAMES · newest at top                  2459.5 MHz")


class ModelImage(QWidget):
    def __init__(self):
        super().__init__()
        self.gray = None
        self.boxes = []
        self.replay = False
        self.setMinimumSize(230, 235)
        self.setMaximumHeight(340)

    def clear(self):
        self.gray = None
        self.boxes = []
        self.update()

    def set_data(self, image, boxes):
        self.gray, self.boxes = image, boxes
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        size = min(self.width() - 20, self.height() - 25)
        rect = QRectF((self.width() - size) / 2, max(1, (self.height() - size - 25) / 2), size, size)
        p.fillRect(rect, QColor("#16181b"))
        if self.gray is None:
            p.setPen(GRID)
            for fraction in (0.25, 0.5, 0.75):
                p.drawLine(QPointF(rect.left() + size * fraction, rect.top()), QPointF(rect.left() + size * fraction, rect.bottom()))
                p.drawLine(QPointF(rect.left(), rect.top() + size * fraction), QPointF(rect.right(), rect.top() + size * fraction))
            p.setPen(MUTED)
            p.setFont(font(10))
            p.drawText(rect, Qt.AlignCenter, "MODEL INPUT\n20 ms / 640 × 640")
        else:
            data = np.ascontiguousarray(self.gray)
            image = QImage(data.data, 640, 640, data.strides[0], QImage.Format_Grayscale8)
            p.drawImage(rect, image)
            if not self.replay:
                p.setPen(QPen(TEAL, 1, Qt.DashLine))
                for fraction in (0.25, 0.75):
                    y = rect.top() + fraction * size
                    p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            for box in self.boxes:
                x0, y0, x1, y1 = box["xyxy"]
                r = QRectF(rect.left() + x0 / 640 * size, rect.top() + y0 / 640 * size,
                           (x1 - x0) / 640 * size, (y1 - y0) / 640 * size)
                color = QColor(COLORS.get(box["class"], "#ffffff"))
                rejected = box["class"] == "drone" and not box["in_target"]
                if rejected:
                    color = QColor("#87939a")
                p.setPen(QPen(color, 1 if rejected else 2, Qt.DashLine if rejected else Qt.SolidLine))
                p.drawRect(r)
                p.setFont(font(8, True))
                label = f"{box['class'].upper()} {box['confidence']:.0%}" + ((" / EDGE" if getattr(self, "survey", False) else " / OFF BAND") if rejected else "")
                width = p.fontMetrics().horizontalAdvance(label) + 10
                tag = QRectF(min(r.left(), rect.right() - width), max(rect.top(), r.top() - 18), width, 18)
                p.fillRect(tag, color)
                p.setPen(QColor("#101619"))
                p.drawText(tag, Qt.AlignCenter, label)
        p.setFont(font(8, True))
        p.setPen(MUTED)
        p.drawText(QRectF(rect.left(), rect.bottom() + 5, size, 20), Qt.AlignCenter,
                   "LAST IQ · 20 ms" if getattr(self, "survey", False) else "RECORDED IMAGE · 20 ms" if self.replay else "0 ms → 20 ms    |    ↑ HIGH FREQUENCY")
