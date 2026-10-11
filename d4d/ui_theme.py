"""Neutral, compact desktop workspaces. Color is reserved for measured state."""
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QSizePolicy, QFrame, QVBoxLayout, QHBoxLayout

STYLE = """
QWidget { background:#202123; color:#d0d2d5; font-family:'Segoe UI'; font-size:12px; }
QMainWindow, QWidget#workspace { background:#151618; }
QFrame#appHeader { background:#28292c; border-bottom:1px solid #101113; }
QFrame#transport { background:#303135; border-bottom:1px solid #161719; }
QFrame#panel, QFrame#card { background:#252629; border:1px solid #141517; border-radius:2px; }
QFrame#panelHeader { background:#303135; border:0; border-bottom:1px solid #17181a; }
QFrame#panelHeader QLabel { background:transparent; font-size:11px; font-weight:600; }
QFrame#panelBody, QFrame#panelBody QWidget, QFrame#card QLabel { background:transparent; }
QLabel { background:transparent; }
QLabel#muted { color:#999ca2; font-size:11px; }
QLabel#eyebrow { color:#aeb1b6; font-size:10px; font-weight:600; }
QLabel#title { color:#ededee; font-size:19px; font-weight:600; }
QLabel#metric { color:#e1e2e5; font:20px 'Consolas'; }
QLabel#badge { color:#b6c2be; background:#252729; border:1px solid #414347; border-radius:2px; padding:5px 9px; font:10px 'Consolas'; }
QPushButton, QToolButton { background:#393b3f; border:1px solid #505258; border-radius:3px; padding:5px 10px; color:#dcdee1; }
QPushButton:hover, QToolButton:hover { background:#484a50; border-color:#73767d; }
QPushButton:pressed, QToolButton:pressed { background:#252629; }
QToolButton:checked { background:#3c4943; border-color:#789285; color:#edf1ee; }
QPushButton:disabled, QToolButton:disabled { color:#676a70; background:#2a2b2e; border-color:#35373b; }
QPushButton#primary { background:#3d514b; border-color:#6c8e80; color:#e1f1e9; font-weight:600; }
QPushButton#primary:hover { background:#4b6259; }
QPushButton#stop { background:#533c37; border-color:#936a5d; color:#f1c1ae; }
QPushButton#page { background:transparent; border:0; border-top:2px solid transparent; border-radius:0; color:#9b9ea4; padding:9px 24px; }
QPushButton#page:checked { background:#303135; border-top-color:#acedd0; color:#eff2ef; }
QPushButton#page:hover { background:#34363a; color:#e6e7e9; }
QFrame#pages, QFrame#statusStrip { background:#252629; border-top:1px solid #111214; }
QFrame#statusStrip QLabel { font-size:10px; color:#a0a3aa; }
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit { background:#202123; color:#d5d7dc; border:1px solid #4a4c52; border-radius:2px; padding:4px 7px; min-height:19px; selection-background-color:#475c56; }
QComboBox:disabled { color:#7c7f85; }
QComboBox QAbstractItemView { background:#303135; border:1px solid #505258; selection-background-color:#475951; }
QComboBox::drop-down { border:0; width:20px; }
QMenuBar { background:transparent; border:0; }
QMenuBar::item { background:transparent; padding:6px 10px; }
QMenuBar::item:selected { background:#414349; }
QMenu { background:#2e3034; border:1px solid #585b62; padding:5px; }
QMenu::item { padding:6px 28px 6px 16px; }
QMenu::item:selected { background:#4a4d53; }
QMenu::item:disabled { color:#777a81; }
QMenu::separator { height:1px; background:#4a4c52; margin:5px; }
QSplitter::handle { background:#141517; }
QSplitter::handle:hover { background:#6a877b; }
QScrollArea { border:0; background:#252629; }
QScrollBar:vertical { background:#1b1c1e; width:9px; margin:0; }
QScrollBar:horizontal { background:#1b1c1e; height:9px; margin:0; }
QScrollBar::handle { background:#4f5157; border-radius:2px; min-height:22px; min-width:22px; }
QScrollBar::handle:hover { background:#71747c; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }
QTabWidget::pane { border:1px solid #151618; background:#252629; }
QTabBar::tab { background:#252629; color:#979ba3; border:0; border-top:2px solid transparent; padding:7px 20px; }
QTabBar::tab:selected { background:#303135; color:#e3e5e8; border-top-color:#9bb5a8; }
QTabBar::tab:hover { color:#edf0ef; }
QTreeWidget, QPlainTextEdit { background:#202123; alternate-background-color:#252629; color:#c9ccd1; border:0; }
QTreeWidget::item { padding:4px 6px; border-bottom:1px solid #2c2e32; }
QTreeWidget::item:selected { background:#3c4c46; color:#f0f3f1; }
QTreeWidget::item:hover { background:#32363a; }
QHeaderView::section { background:#2d2f33; color:#a9adb5; border:0; border-right:1px solid #222428; border-bottom:1px solid #17181a; padding:6px; font-size:10px; }
QToolTip { background:#3d4046; color:#eff0f2; border:1px solid #656970; padding:6px; }
QDialog { background:#252629; }
"""


class ElidedLabel(QLabel):
    """Keep full text accessible while long telemetry yields width to controls."""
    def __init__(self, text='', role='muted'):
        super().__init__(text)
        self.setObjectName(role)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(self.palette().windowText().color())
        rect = self.contentsRect()
        p.drawText(rect, self.alignment(),
                   self.fontMetrics().elidedText(self.text().replace('\n', ' · '), Qt.ElideRight, rect.width()))


def panel(title, trailing=None):
    frame = QFrame()
    frame.setObjectName('panel')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    head = QFrame()
    head.setObjectName('panelHeader')
    row = QHBoxLayout(head)
    row.setContentsMargins(10, 5, 10, 5)
    row.addWidget(QLabel(title))
    if trailing is not None:
        if isinstance(trailing, QLabel):
            trailing.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(trailing, 1)
    else:
        row.addStretch()
    layout.addWidget(head)
    body = QFrame()
    body.setObjectName('panelBody')
    col = QVBoxLayout(body)
    col.setContentsMargins(10, 8, 10, 8)
    col.setSpacing(7)
    layout.addWidget(body, 1)
    return frame, col


def icon(name):
    """Small original line icons with a consistent 20-unit grid."""
    paths = {
        'survey': '<circle cx="10" cy="10" r="7"/><circle cx="10" cy="10" r="3"/><path d="M10 10l5-5M10 1v2M1 10h2M10 17v2M17 10h2"/>',
        'live': '<path d="M2 12h3l2-7 4 11 2-7 2 3h3"/>',
        'replay': '<rect x="3" y="3" width="14" height="14" rx="1"/><path d="M8 6l6 4-6 4z"/>',
        'inspector': '<rect x="2" y="3" width="16" height="14" rx="1"/><path d="M12 3v14M14 7h2M14 10h2M14 13h2"/>',
        'records': '<rect x="2" y="3" width="16" height="14" rx="1"/><path d="M2 8h16M2 12h16M7 3v14"/>',
        'folder': '<path d="M2 5h6l2 2h8v10H2zM2 7V3h6l2 2h6v2"/>',
    }
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20"><g fill="none" stroke="#bac1c7" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</g></svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for size in (20, 40, 60):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result
