"""Observation-first adaptive survey dashboard. Historical evidence stays labelled."""
import time
import json
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSplitter, QLineEdit, QPushButton,
    QDialog, QDialogButtonBox, QPlainTextEdit, QTabWidget, QFormLayout)
from .ui_theme import panel, ElidedLabel
from .widgets import ModelImage, Spectrum, font, MUTED, GRID, TEAL


class SurveyMap(QWidget):
    def __init__(self):
        super().__init__()
        self.sweep = None
        self.center = None
        self.low, self.high = 1, 6000
        self.ranges = ((1, 6000),)
        self.path_key = self.cached_path = None
        self.setMinimumHeight(120)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(font(8, True))
        stacked = self.width() < 590 and len(self.ranges) > 1
        panel_width = self.width() if stacked else self.width() / len(self.ranges)
        panel_height = self.height() / len(self.ranges) if stacked else self.height()
        key = (self.sweep['ended'] if self.sweep else None, self.width(), self.height(), tuple(self.ranges))
        if key != self.path_key:
            self.cached_path, self.path_key = {}, key
        for panel, (low, high) in enumerate(self.ranges):
            left = 0 if stacked else panel * panel_width
            top = panel * panel_height if stacked else 0
            r = QRectF(left + 38, top + 23, panel_width - 49, panel_height - 47)
            p.fillRect(r, QColor("#191b1e"))
            p.setPen(MUTED)
            p.drawText(QRectF(left + 38, top, panel_width - 48, 20), f"{low}–{high} MHz  /  dBFS/bin")
            ticks = (-100, -60, -20) if r.height() < 90 else (-100, -80, -60, -40, -20)
            for db in ticks:
                y = r.bottom() - (db + 110) / 100 * r.height()
                p.setPen(GRID)
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                p.setPen(MUTED)
                p.drawText(QRectF(left, y - 8, 34, 18), Qt.AlignRight, str(db))
            for i in range(5):
                x = r.left() + r.width() * i / 4
                p.setPen(MUTED)
                p.drawText(QRectF(x - 30, r.bottom() + 7, 60, 20), Qt.AlignCenter, f"{low + (high-low)*i/4:.0f}")
            def x_at(freq):
                return r.left() + (freq - low) / (high - low) * r.width()
            if self.sweep and panel not in self.cached_path:
                values = self.sweep['power'][low-self.sweep['low']:high-self.sweep['low']]
                pixels = max(1, min(len(values), int(r.width())))
                edges = np.linspace(0, len(values), pixels + 1).astype(int)
                maxima = np.maximum.reduceat(np.where(np.isfinite(values), values, -110), edges[:-1])
                ys = r.bottom() - np.clip((maxima + 110) / 100, 0, 1) * r.height()
                path = QPainterPath()
                for a, b, y in zip(edges[:-1], edges[1:], ys):
                    x = x_at(low + (a + b) / 2)
                    path.moveTo(x, r.bottom())
                    path.lineTo(x, float(y))
                self.cached_path[panel] = path
            if self.sweep:
                p.setPen(QPen(QColor("#8caaa1"), 1))
                p.drawPath(self.cached_path[panel])
                for c in self.sweep['candidates']:
                    if low <= c['center_mhz'] < high:
                        p.fillRect(QRectF(x_at(c['center_mhz']) - 1, r.top(), 2, 7), QColor('#e4cf8b'))
            else:
                p.setPen(MUTED)
                p.drawText(r, Qt.AlignCenter, '미관측 · 스윕 시작 대기')
            if self.center is not None and low <= self.center < high:
                x = x_at(self.center)
                p.setPen(QPen(QColor('#ffab83'), 2))
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))


class SurveyPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.latest = None
        self.last_visits = -1
        self.last_zoom_end = None
        self.next_age_refresh = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        self.views = QSplitter(Qt.Horizontal)
        self.views.setChildrenCollapsible(False)
        self.views.setHandleWidth(4)
        self.scopes = QSplitter(Qt.Vertical)
        self.scopes.setChildrenCollapsible(False)
        self.scopes.setHandleWidth(4)
        self.coverage = ElidedLabel('미관측')
        self.coverage.setMinimumWidth(180)
        overview, col = panel('대역 탐색 / SPECTRUM', self.coverage)
        self.map = SurveyMap()
        self.map.setMinimumHeight(150)
        col.addWidget(self.map,1)
        self.scope_note = ElidedLabel('선택 대역 순차 관측 · 동시 감시 아님')
        col.addWidget(self.scope_note)
        self.scopes.addWidget(overview)
        zoom_scope, detail = panel('최근 IQ 스펙트럼', QLabel('20 MHz'))
        self.spectrum = Spectrum()
        self.spectrum.survey = True
        self.spectrum.setMinimumHeight(90)
        detail.addWidget(self.spectrum,1)
        self.quality = ElidedLabel('입력 품질 측정 대기')
        detail.addWidget(self.quality)
        self.scopes.addWidget(zoom_scope)
        self.views.addWidget(self.scopes)
        zoom, viewer = panel('모델 입력 / 검출 박스', QLabel('640 × 640'))
        zoom.setMinimumWidth(270)
        self.zoom_title = ElidedLabel('최근 IQ 관측 대기')
        self.zoom_title.setStyleSheet("font:12px 'Consolas'; color:#d8dbe0;")
        viewer.addWidget(self.zoom_title)
        self.image = ModelImage()
        self.image.replay = True
        self.image.survey = True
        self.image.setMinimumSize(210,210)
        self.image.setMaximumHeight(16777215)
        viewer.addWidget(self.image,1)
        self.evidence = QLabel('후보 대역의 IQ를 분석하면 검출 근거가 표시됩니다.')
        self.evidence.setWordWrap(True)
        self.evidence.setObjectName('muted')
        self.evidence.setMinimumHeight(65)
        viewer.addWidget(self.evidence)
        self.views.addWidget(zoom)
        layout.addWidget(self.views,1)
        self.phase = ElidedLabel('SWEEP → SELECT → ZOOM → REVISIT')
        self.phase.setStyleSheet("font:10px 'Consolas'; color:#b7beb9; padding:3px;")
        self.phase.setFixedHeight(23)
        layout.addWidget(self.phase)
        self.records_panel = QWidget()
        records = QVBoxLayout(self.records_panel)
        records.setContentsMargins(0,0,0,0)
        records.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(10,5,10,5)
        self.count = ElidedLabel('관측 기록 · 0')
        row.addWidget(self.count,1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('기록 / 주파수 / 분류 검색')
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(195)
        self.filter.textChanged.connect(self.apply_filter)
        row.addWidget(self.filter)
        self.details_button = QPushButton('관측 상세')
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(self.show_record_details)
        row.addWidget(self.details_button)
        records.addLayout(row)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setMinimumHeight(60)
        self.table.setColumnCount(10)
        self.table.setHeaderLabels(['기록 / MHz','형태 분류 · 근거','최초 / 최근 UTC','관측 / 유효','관측 공백','전력 변화','단일/짝 점수','방문','누산 / 회차','품질 / 학습 범위'])
        self.table.header().setSectionResizeMode(QHeaderView.Interactive)
        for index,width in enumerate((137,185,132,112,103,78,90,48,98,225)):
            self.table.setColumnWidth(index,width)
        self.table.header().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(lambda: self.details_button.setEnabled(bool(self.table.selectedItems())))
        self.table.itemDoubleClicked.connect(lambda *_: self.show_record_details())
        records.addWidget(self.table,1)
        self.warning = ElidedLabel('기록 번호 ≠ 기기 ID · 관측 공백의 존재/소멸은 미확인 · 전력/박스가 없어도 신호 부재를 확정하지 않습니다.')
        self.warning.setContentsMargins(10,3,10,3)
        records.addWidget(self.warning)

    def apply_filter(self):
        query=self.filter.text().strip().casefold()
        for index in range(self.table.topLevelItemCount()):
            item=self.table.topLevelItem(index)
            item.setHidden(bool(query) and query not in ' '.join(item.text(c) for c in range(10)).casefold())

    def show_record_details(self):
        selected=self.table.selectedItems()
        if not selected:
            return
        record=selected[0].data(0,Qt.UserRole)
        dialog=QDialog(self)
        dialog.setWindowTitle(f"관측 상세 · {record['id']}")
        dialog.resize(660,520)
        col=QVBoxLayout(dialog)
        note=QLabel('저장된 관측 근거 · 현재 송신 상태 또는 기기 ID를 의미하지 않습니다.')
        note.setWordWrap(True)
        col.addWidget(note)
        tabs=QTabWidget()
        summary=QWidget()
        form=QFormLayout(summary)
        form.setSpacing(14)
        evidence=record.get('evidence')
        fields=[('관측 번호',record['id']),('주파수 구간',f"{record['low_mhz']:.3f}–{record['high_mhz']:.3f} MHz"),
                ('판정 근거',record['assessment']),('최초 관측',record['first_utc']),('최근 관측',record['last_utc']),
                ('실제 IQ 표본 시간',f"{record['observed_seconds']:.3f} s · 유효 {record['valid_seconds']:.3f} s"),
                ('누산 근거',f"{evidence['score']:.2f} / {evidence['episodes']}회차 · 확률 아님" if evidence else '없음'),
                ('입력 품질',', '.join(record['quality_flags']) or '품질 경고 없음'),('학습 범위',record['model_domain'])]
        for title,value in fields:
            item=QLabel(str(value))
            item.setWordWrap(True)
            item.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(title,item)
        tabs.addTab(summary,'관측 요약')
        text=QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(record,ensure_ascii=False,indent=2))
        text.setStyleSheet("font:12px 'Consolas';")
        tabs.addTab(text,'원본 근거 / JSON')
        col.addWidget(tabs,1)
        buttons=QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        dialog.exec()

    def clear(self, low, high, ranges=None):
        self.latest = None
        self.last_visits = -1
        self.last_zoom_end = None
        self.map.low, self.map.high = low, high
        self.map.ranges = tuple(ranges or [(low, high)])
        self.map.sweep = self.map.center = None
        self.map.update()
        self.image.clear()
        self.spectrum.clear()
        self.table.clear()
        self.count.setText("관측 기록 · 0")
        self.coverage.setText("미관측")
        self.zoom_title.setText("최근 IQ 관측 대기")
        self.evidence.setText("수신 시작을 기다립니다.")
        self.quality.setText('입력 품질 측정 대기')
        self.phase.setText('SWEEP → SELECT → ZOOM → REVISIT')
        self.scope_note.setText(' / '.join(f'{a}–{b} MHz' for a,b in self.map.ranges) + ' · 순차 관측')

    def render(self, f):
        self.latest = f
        phase = f["phase"]
        names = {"SWEEP": "01  SWEEP / 선택 대역 탐색", "SELECT": "02  SELECT / 관측 순서 선정",
                 "ZOOM": "03  ZOOM / 고정 수신 + IQ 분석", "REVISIT": "04  REVISIT / 근거 기록 + 재방문"}
        self.phase.setText(f"{names[phase]}    ·    CYCLE {f['cycle']:04d}")
        self.map.low, self.map.high = f["survey_low"], f["survey_high"]
        self.map.ranges = tuple(tuple(r) for r in f.get('survey_ranges', [(f['survey_low'], f['survey_high'])]))
        self.map.sweep = f["sweep"]
        self.map.center = f.get("active_center_mhz")
        self.map.update()
        self.scope_note.setText(f"{f.get('survey_profile', 'SURVEY')} · " + ' / '.join(f'{a}–{b} MHz' for a,b in self.map.ranges) +
                               ' · 선택 구간만 순차 관측 / 중간 대역 제외' if len(self.map.ranges) > 1 else '전체 또는 사용자 지정 구간 순차 관측')
        if f.get('survey_channel_mhz')==20:
            self.scope_note.setText(self.scope_note.text()+' · 20 MHz 채널은 부분 창 순차 확인')
        if f["sweep"]:
            s = f["sweep"]
            flags = ", ".join(s["quality_flags"]) or "품질 경고 없음"
            self.coverage.setText(f"타일 관측 {s['coverage_pct']:.1f}% · {s['seconds']:.2f} s / sweep · {flags}")
        z = f["zoom"]
        if z and z["ended"] != self.last_zoom_end:
            self.last_zoom_end = z["ended"]
            row = z["record"]
            evidence = row.get('evidence')
            evidence_text = (f"누산 {evidence['score']:.2f} / {evidence['episodes']}회차 · {evidence['state']}" if evidence else '누산 근거 대기')
            self.zoom_title.setText(f"{row['id']}   /   {z['center_mhz']:.3f} MHz")
            pair = row.get('partial_pair')
            score_text = (f"부분 짝 최소 점수 {pair['confidence']:.3f}" if pair else
                          f"단일 창 유효 drone 점수 {row['drone_score']:.3f}")
            self.evidence.setText(f"{row['assessment']} · {score_text}\n"
                f"이번 방문 {z['frames']} × 20 ms · 누적 관측 {row['observed_seconds']:.3f} s · {row['model_domain']}\n"
                + evidence_text + " · 확률 아님\n마지막 IQ 관측 기록 / 현재 존재 여부는 재방문 전까지 미확인")
            self.image.set_data(z["image"], z["boxes"])
            if getattr(self.spectrum, "center_mhz", None) != z["center_mhz"]:
                self.spectrum.clear()
            self.spectrum.center_mhz = z["center_mhz"]
            self.spectrum.set_data(z["spectrum"])
            self.quality.setText(f"IQ {z['signal']['rms_dbfs']:.1f} dBFS · CLIP {z['signal']['clipped_pct']:.3f}% · "
                f"추론 {z['inference_ms']:.1f} ms · " + (", ".join(z["quality_flags"]) or "입력 품질 경고 없음") +
                "\n형태 분류만 수행 · 표준 프로토콜 및 송신기 식별 미확인")
        self.count.setText(f"관측 {f['total_records']}개 · {f['visits']} visits · {f['processed']} frames")
        if f["visits"] == self.last_visits:
            return
        self.last_visits = f["visits"]
        selected=self.table.selectedItems()
        selected_id=selected[0].data(0,Qt.UserRole)['id'] if selected else None
        scroll=self.table.verticalScrollBar().value()
        self.table.setUpdatesEnabled(False)
        self.table.clear()
        for record in f["observations"][:80]:
            delta = record["power_delta_db"]
            evidence = record.get('evidence')
            item = QTreeWidgetItem([
                f"{record['id']}\n{record['low_mhz']:.1f}–{record['high_mhz']:.1f}",
                record["assessment"],
                record["first_utc"][11:19] + " / " + record["last_utc"][11:19],
                f"{record['observed_seconds']:.3f} / {record['valid_seconds']:.3f} s",
                f"{record['since_last_seconds']:.1f} s · 미확인",
                "비교 대기" if delta is None else f"{delta:+.1f} dB",
                (f"{record['partial_pair']['confidence']:.3f} 짝" if record.get('partial_pair') else
                 f"{record['drone_score']:.3f}"), str(record["visits"]),
                f"{evidence['score']:.2f} / {evidence['episodes']}회" if evidence else '—',
                (", ".join(record["quality_flags"]) or "양호") + " / " + record["model_domain"]])
            item.setToolTip(1, str(record["basis"]))
            item.setToolTip(3, "관측한 IQ 표본 시간 / 입력 품질 기준을 통과한 표본 시간. 송신 지속 시간이 아닙니다.")
            item.setToolTip(5, "같은 중심 주파수·gain·필터의 직전 유효 방문 대비 전체 20 MHz IQ RMS 변화. dBm이 아닙니다.")
            item.setToolTip(6, '단일 창의 유효 drone 점수 또는 성립한 부분 짝의 최소 점수. 원본 박스 점수는 이미지·로그에 별도 보존합니다.')
            item.setToolTip(8, '회차당 기여 상한 1 · 8초 반감기 · 3회차 이상 · 누산은 확률 또는 기기 ID가 아닙니다.')
            if evidence and evidence['supported']:
                item.setForeground(8, QColor('#91e7cc'))
            if record["repeated_drone_shape"]:
                item.setForeground(1, QColor("#ffab83"))
            item.setData(0,Qt.UserRole,record)
            self.table.addTopLevelItem(item)
            if record['id']==selected_id:
                item.setSelected(True)
        self.apply_filter()
        self.table.verticalScrollBar().setValue(scroll)
        self.table.setUpdatesEnabled(True)

    def refresh_ages(self):
        if not self.latest:
            return
        if time.perf_counter() < self.next_age_refresh:
            return
        self.next_age_refresh = time.perf_counter() + 1
        rows = self.latest["observations"][:80]
        now = time.perf_counter()
        if self.latest["sweep"]:
            s = self.latest["sweep"]
            flags = ", ".join(s["quality_flags"]) or "품질 경고 없음"
            self.coverage.setText(f"최근 스윕 {max(0, now - s['ended']):.1f}초 전 · 타일 {s['coverage_pct']:.1f}% · {s['seconds']:.2f} s · {flags}")
        for i, row in enumerate(rows):
            self.table.topLevelItem(i).setText(4, f"{max(0, now - row['last_mono']):.1f} s · 미확인")
