"""A small observation-window / wave motif, separate from the product logo."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel


class StatusTag(QLabel):
    """Text remains the status authority; the static trace is a state symbol."""
    def __init__(self, text='STANDBY', boxed=False):
        super().__init__(text)
        self.state = 'IDLE'
        self.boxed = boxed
        self.color = QColor('#8da4b1')
        self.setIndent(28)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if boxed:
            self.setObjectName('badge')
        self.set_status(text, 'IDLE', '#8da4b1')

    def set_status(self, text, state, color='#8da4b1'):
        self.state = state
        self.color = QColor(color)
        self.setText(text)
        if self.boxed:
            self.setStyleSheet(f'color:{color};')
        else:
            self.setStyleSheet(f'background:transparent; border:0; color:{color}; font-size:10px; font-weight:600;')
        self.setAccessibleName(text)
        self.setToolTip(text + ' · 관측 창과 파형으로 표현한 상태 기호입니다. 실측 파형이 아닙니다.')
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(8 if self.boxed else 0, (self.height() - 16) / 2)
        active = self.state not in ('IDLE', 'STOPPED', 'STOPPING')
        detected = self.state == 'DETECTED'
        held = self.state in ('QUALITY', 'STALE', 'GAP', 'ERROR', 'DEGRADED')
        frame = QColor(self.color)
        frame.setAlpha(210 if detected else 105)
        p.setPen(QPen(frame, 1.2, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        # Open corners define an observation window, without a circular LED.
        for x, direction in ((1, 1), (23, -1)):
            p.drawLine(x, 1, x + direction * 4, 1)
            p.drawLine(x, 1, x, 4)
            p.drawLine(x, 15, x + direction * 4, 15)
            p.drawLine(x, 12, x, 15)
        p.setPen(QPen(self.color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        trace = QPainterPath()
        if self.state in ('STOPPED', 'STOPPING'):
            p.drawLine(9, 5, 9, 11)
            p.drawLine(15, 5, 15, 11)
        elif held:
            trace.moveTo(4, 7)
            trace.lineTo(7, 11)
            trace.lineTo(9, 7)
            trace.moveTo(15, 9)
            trace.lineTo(18, 5)
            trace.lineTo(21, 7)
        elif active:
            trace.moveTo(4, 7)
            trace.cubicTo(6, 7, 6, 11, 8, 11)
            trace.cubicTo(10, 11, 10, 5, 12, 5)
            trace.cubicTo(14, 5, 14, 11, 16, 11)
            trace.cubicTo(18, 11, 18, 7, 20, 7)
        else:
            trace.moveTo(7, 8)
            trace.lineTo(17, 8)
        p.drawPath(trace)
        if detected:
            p.drawLine(9, 15, 15, 15)
