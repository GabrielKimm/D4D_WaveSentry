"""Small adapter consuming the same verdicts the existing workstation displays."""
import os
import time
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QFrame
from .config import ROOT
from .nu87 import IndicatorClient, should_alarm


class Nu87Indicator(QObject):
    def __init__(self, window, client=None):
        super().__init__(window)
        self.window = window
        self.closed = False
        self.test_until = 0
        self.last_status = None
        self.client = client or IndicatorClient(log_path=ROOT / 'runtime/nu87-indicator.jsonl')
        self.configured = bool(os.environ.get('D4D_NU87_SERIAL', '').strip())
        self.enabled = os.environ.get('D4D_NU87_DISABLED') != '1' and self.configured
        self.label = QLabel('NU-87 · 연결 확인 중')
        self.label.setObjectName('nu87Indicator')
        self.label.setToolTip('USB 드론 경보 · 빨강 최대 밝기 / 5 Hz\n탐지 및 관측 상태와 연동')
        window.findChild(QFrame, 'statusStrip').layout().addWidget(self.label)
        self.test_action = QAction('NU-87 빨간 LED 테스트 (3초)', window)
        self.test_action.triggered.connect(self.test)
        self.test_action.setEnabled(False)
        self.label.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.label.addAction(self.test_action)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)
        if self.enabled:
            self.client.start()

    def test(self):
        self.test_until = time.monotonic() + 3
        self.refresh()

    def requested_alarm(self):
        w = self.window
        if w.closing or self.closed:
            return False
        mode = w.mode.currentData()
        if mode == 'demo':
            d = w.demo_panel
            return should_alarm(mode, running=d.active and d.model.running,
                                demo_stale=d.model.stale, tracks=d.current_tracks)
        running = bool(w.thread and w.thread.is_alive() and w.engine
                       and not w.engine.stop_event.is_set())
        if mode == 'survey':
            # Evaluate time decay now, including stale/quality/lifecycle suppression.
            state = w.survey_dashboard.model.evaluate(time.perf_counter())['state']
            return should_alarm(mode, running=running, state=state, fresh=True)
        return should_alarm(mode, running=running, state=w.current_state,
                            fresh=bool(w.last_seen and time.monotonic() - w.last_seen <= 1.2))

    def refresh(self):
        if self.closed:
            return
        if not self.enabled:
            self.label.setText('NU-87 · 비활성' if self.configured else 'NU-87 · 미설정')
            self.label.setToolTip('연결할 보드의 USB 시리얼을 설정하세요. 자세한 내용은 docs/SETUP.md를 참고하세요.')
            return
        self.client.update(self.requested_alarm() or (not self.window.closing and time.monotonic() < self.test_until))
        status = self.client.status
        names = dict(SEARCHING='연결 확인 중', CONNECTING='연결 중', DISCONNECTED='연결 안 됨',
                     ERROR='연결 확인 필요', CLOSED='종료')
        simulated = self.window.mode.currentData() in ('demo', 'replay')
        text = ('경보' if simulated else '탐지 경보') if status.alarm else '대기'
        if time.monotonic() < self.test_until and status.alarm:
            text = 'LED 테스트'
        self.label.setText(f'NU-87 · {text}' if status.state == 'CONNECTED' else 'NU-87 · ' + names[status.state])
        self.label.setStyleSheet('color:#ff735f;font-weight:600;' if status.alarm else 'color:#98b9ae;')
        self.label.setToolTip(f'{status.port or "USB 자동 검색"} · {status.detail or "빨강 최대 밝기 · 5 Hz"}\n'
                             '오른쪽 클릭: LED 테스트 (3초)\n모니터링·녹화 분석에서도 경보 LED가 동작합니다.')
        self.test_action.setEnabled(status.state == 'CONNECTED')
        if status != self.last_status:
            self.window.add_event('NU-87', self.label.text() + ' · ' + (status.port or status.detail))
            self.last_status = status

    def close(self):
        self.closed = True
        self.timer.stop()
        self.client.close()
