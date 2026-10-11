from datetime import datetime
import json
import threading
import time
from PySide6.QtCore import QTimer, QUrl, Signal, QObject
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QLabel, QVBoxLayout, QComboBox,
    QDialog, QFormLayout, QDoubleSpinBox, QSpinBox, QDialogButtonBox, QTreeWidgetItem)
from .config import ROOT, Settings, read_settings, save_settings
from .engine import Engine
from .survey_engine import SurveyEngine
from .survey_dashboard import STATES as SURVEY_STATES
from .branding import WINDOW_TITLE, app_icon

from .ui_theme import STYLE
from .workstation import build_workspace


def label(text, role=None):
    w = QLabel(text)
    if role:
        w.setObjectName(role)
    return w



class Bridge(QObject):
    status = Signal(dict)


class SettingsDialog(QDialog):
    def __init__(self, current, parent):
        super().__init__(parent)
        self.setWindowTitle("수신 및 추론 설정")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.addWidget(label("수신 · 관측 프로필", "title"))
        layout.addWidget(label("LIVE 2449.5 MHz · 수신 20 MS/s · AMP / Bias-T OFF", "muted"))
        form = QFormLayout()
        self.lna, self.vga, self.backend = QComboBox(), QComboBox(), QComboBox()
        for gain in range(0, 41, 8):
            self.lna.addItem(f"{gain} dB", gain)
        for gain in range(0, 63, 2):
            self.vga.addItem(f"{gain} dB", gain)
        for name, value in (("자동 · Intel GPU 우선", "AUTO"), ("Intel GPU · OpenVINO", "GPU"),
                            ("CPU · OpenVINO", "CPU"), ("CPU · PyTorch 원본", "TORCH")):
            self.backend.addItem(name, value)
        self.lna.setCurrentIndex(self.lna.findData(current.lna))
        self.vga.setCurrentIndex(self.vga.findData(current.vga))
        self.backend.setCurrentIndex(self.backend.findData(current.backend))
        self.conf = QDoubleSpinBox()
        self.conf.setRange(0.05, 0.95)
        self.conf.setSingleStep(0.05)
        self.conf.setValue(current.confidence)
        form.addRow("LNA / IF gain", self.lna)
        form.addRow("VGA / baseband gain", self.vga)
        form.addRow("추론 장치", self.backend)
        form.addRow("박스 신뢰도 기준", self.conf)
        self.survey_profile = QComboBox()
        for text, value in (("2.4 / 5 GHz 안테나 · 기본", "antenna_24_5"),
                            ("전체 1–6000 MHz · 확장 관측", "full"), ("사용자 지정 연속 범위", "custom")):
            self.survey_profile.addItem(text, value)
        self.survey_profile.setCurrentIndex(self.survey_profile.findData(current.survey_profile))
        form.addRow("SURVEY 관측 프로필", self.survey_profile)
        self.channel_width = QComboBox()
        self.channel_width.addItem('20 MHz · 겹치는 부분 창 확인',20)
        self.channel_width.addItem('10 MHz · 단일 창 재중심 확인',10)
        self.channel_width.setCurrentIndex(self.channel_width.findData(current.survey_channel_mhz))
        form.addRow('SURVEY 대상 채널 폭',self.channel_width)
        self.survey_low, self.survey_high, self.survey_zooms = QSpinBox(), QSpinBox(), QSpinBox()
        self.survey_low.setRange(1, 5999)
        self.survey_high.setRange(2, 6000)
        self.survey_low.setValue(current.survey_low)
        self.survey_high.setValue(current.survey_high)
        self.survey_low.setMaximum(current.survey_high - 1)
        self.survey_high.setMinimum(current.survey_low + 1)
        self.survey_low.valueChanged.connect(lambda value: self.survey_high.setMinimum(value + 1))
        self.survey_high.valueChanged.connect(lambda value: self.survey_low.setMaximum(value - 1))
        self.survey_zooms.setRange(2, 8)
        self.survey_zooms.setValue(current.survey_zooms)
        self.survey_threshold = QDoubleSpinBox()
        self.survey_threshold.setRange(3, 20)
        self.survey_threshold.setValue(current.survey_threshold_db)
        form.addRow("SURVEY 시작 MHz", self.survey_low)
        form.addRow("SURVEY 끝 MHz", self.survey_high)
        form.addRow("기본 IQ 방문 / 사이클", self.survey_zooms)
        form.addRow("전력 후보 기준 dB", self.survey_threshold)
        def scope_enabled():
            custom = self.survey_profile.currentData() == 'custom'
            self.survey_low.setEnabled(custom)
            self.survey_high.setEnabled(custom)
        self.survey_profile.currentIndexChanged.connect(scope_enabled)
        scope_enabled()
        layout.addLayout(form)
        note = label("안테나 프로필: 2400–2500 / 5150–5890 MHz만 순차 관측\nSURVEY: 방문 간 주파수 근거 누산 · 시간 감쇠 · 후보 즉시 재확인\n고정 LIVE: 0.75초 내 최근 3회 중 2회 · 해제 1.2초\n모델 점수와 누산 점수는 실제 드론 존재 확률이 아닙니다.", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.serial = current.serial

    def settings(self):
        return Settings(self.lna.currentData(), self.vga.currentData(), self.conf.value(), self.backend.currentData(), self.serial,
                        self.survey_low.value(), self.survey_high.value(), self.survey_zooms.value(), self.survey_threshold.value(),
                        self.survey_profile.currentData(), self.channel_width.currentData())


class MainWindow(QMainWindow):
    def __init__(self, restore_layout=True):
        super().__init__()
        self.persist_layout = restore_layout
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1500, 960)
        self.setMinimumSize(1130, 790)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(app_icon())
        self.settings = read_settings()
        self.engine = self.thread = None
        self.latest = None
        self.pending = None
        self.frame_lock = threading.Lock()
        self.last_seen = 0
        self.current_state = "IDLE"
        self.last_event_state = ""
        self.last_dashboard_state = None
        self.closing = False
        self.bridge = Bridge()
        self.bridge.status.connect(self.on_status)
        build_workspace(self)
        self.mode_changed()
        if restore_layout:
            self.restore_layout()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.add_event("STANDBY", "관측 대기 · 수신 시작 시 HackRF와 모델 02a를 초기화합니다.")
        from .nu87_gui import Nu87Indicator
        self.nu87_indicator = Nu87Indicator(self)

    def choose_mode(self, index):
        if self.thread and self.thread.is_alive():
            self.add_event("INFO", "입력 전환은 수신 중지 후 가능합니다.")
            return
        self.mode.setCurrentIndex(index)

    def mode_changed(self):
        demo = self.mode.currentData() == 'demo'
        self.demo_site.setVisible(demo)
        self.records_stack.setCurrentIndex(1 if demo else 0)
        self.events_stack.setCurrentIndex(1 if demo else 0)
        if demo:
            with self.frame_lock:
                self.pending = None
            self.page_title.setText('실시간 모니터링')
            self.view_stack.setCurrentIndex(2)
            self.inspector_stack.setCurrentIndex(2)
            self.drawer.setTabEnabled(0, True)
            self.drawer.setCurrentIndex(0)
            self.page_buttons[3].setChecked(True)
            self.drawer.setMinimumHeight(260)
            self.snapshot_button.setEnabled(False)
            self.survey_save.setEnabled(False)
            self.demo_panel.activate()
            self.refresh_demo_chrome()
            return
        self.demo_panel.deactivate()
        self.drawer.setMinimumHeight(190)
        self.source_label.setText('RX ONLY')
        self.health.setText('장치 대기 · RF AMP OFF · Bias-T OFF')
        self.backend_label.setText('LOCAL INFERENCE / WaveSentry')
        replay = self.mode.currentData() == "replay"
        survey = self.mode.currentData() == "survey"
        self.badge.set_status('STANDBY', 'IDLE')
        self.page_title.setText("안테나 탐색" if survey else "녹화 분석" if replay else "고정 대역")
        self.view_stack.setCurrentIndex(1 if survey else 0)
        self.inspector_stack.setCurrentIndex(1 if survey else 0)
        self.drawer.setTabEnabled(0, survey)
        self.drawer.setCurrentIndex(0 if survey else 1)
        self.page_buttons[self.mode.currentIndex()].setChecked(True)
        self.survey_dashboard.setVisible(survey)
        self.metrics_container.setVisible(not survey)
        self.survey_dashboard.reset(self.settings.survey_ranges)
        self.fixed_body.setVisible(not survey)
        self.survey_panel.setVisible(survey)
        self.survey_save.setVisible(survey)
        self.survey_save.setEnabled(False)
        ranges = self.settings.survey_ranges
        self.survey_panel.clear(ranges[0][0], ranges[-1][1], ranges)
        self.subtitle.setText(self.settings.survey_label + f" · 대상 {self.settings.survey_channel_mhz} MHz / 스윕 → 부분 창 확인 → 근거 누산" if survey else
                              "녹화 이미지 분석 / REPLAY" if replay else "고정 대역 드론 탐지 / 2444.5–2454.5 MHz")
        for key, title in zip(self.metric_titles, ("01 / SURVEY RANGE", "02 / OBSERVATIONS", "03 / INFERENCE", "04 / SWEEP TIME") if survey else
                ("01 / CENTER FREQUENCY", "02 / TARGET BANDWIDTH", "03 / INFERENCE", "04 / ANALYSIS RATE")):
            self.metric_titles[key].setText(title)
        self.metrics["frequency"][0].setText(("2.4 / 5" if len(ranges) > 1 else f"{ranges[0][0]}–{ranges[0][1]}") if survey else "2449.500")
        self.metrics["frequency"][1].setText(("GHz · 안테나 전용 / 전체 대역 OFF" if len(ranges) > 1 else "MHz · 순차 관측 범위") if survey else "MHz · 고정 주파수 / 호핑 없음")
        self.metrics["band"][0].setText("0" if survey else "10.000")
        self.metrics["band"][1].setText("관측 기록 · 기기 수 아님" if survey else "MHz · 수신 샘플링 20 MS/s")
        self.metrics["coverage"][0].setText("—")
        self.metrics["coverage"][1].setText("s · 전체 범위 스윕 시간" if survey else "fps · 최신 프레임 분석")
        self.spectrum.replay = self.model_image.replay = replay
        self.spectrum.clear()
        self.waterfall.clear()
        self.model_image.clear()
        self.latest = None
        self.start_button.setText("▶  샘플 재생" if replay else "▶  수신 시작")
        self.snapshot_button.setText("↓  이미지 + 분석 저장" if replay else "↓  현재 IQ + 분석 저장")
        self.set_assessment("IDLE", 0)

    def refresh_demo_chrome(self):
        if self.mode.currentData() != 'demo':
            return
        model = self.demo_panel.model
        tag = 'LAST' if model.stale else 'LIVE'
        self.badge.set_status(tag, 'SCANNING' if not model.stale else 'STALE', '#a4dcc8' if not model.stale else '#9aa9b0')
        self.subtitle.setText('고정 RF 어레이 · 연속 추적')
        self.start_button.setEnabled(True)
        self.start_button.setText('■  수신 중지' if model.running else '▶  수신 시작')
        self.start_button.setObjectName('primary')
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.source_label.setText('TRACKING')
        self.health.setText('위치 · 속도 · 진행 방향 · RF 분류')
        self.backend_label.setText('CONTINUOUS TRACKING / WaveSentry')

    def open_settings(self):
        if self.mode.currentData() == 'demo':
            self.demo_panel.open_settings()
            return
        if self.thread and self.thread.is_alive():
            return
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings = dialog.settings()
            save_settings(self.settings)
            self.box_detail.setText(f"model_02a_picked.pt · threshold {self.settings.confidence:.2f}")
            self.add_event("SETTINGS", f"LNA {self.settings.lna} / VGA {self.settings.vga} dB · {self.settings.backend}")
            self.mode_changed()

    def toggle(self):
        if self.mode.currentData() == 'demo':
            self.demo_panel.toggle()
            return
        if self.thread and self.thread.is_alive():
            self.engine.stop()
            if self.mode.currentData() == 'survey':
                self.survey_dashboard.set_lifecycle('STOPPING')
            self.start_button.setEnabled(False)
            self.start_button.setText("중지 중…")
            self.snapshot_button.setEnabled(False)
            self.survey_save.setEnabled(False)
            return
        self.latest = self.pending = None
        self.last_seen = 0
        self.last_event_state = ""
        self.last_dashboard_state = None
        self.spectrum.clear()
        self.waterfall.clear()
        self.model_image.clear()
        cls = SurveyEngine if self.mode.currentData() == "survey" else Engine
        if cls is SurveyEngine:
            ranges = self.settings.survey_ranges
            self.survey_panel.clear(ranges[0][0], ranges[-1][1], ranges)
            self.survey_dashboard.reset(ranges)
            self.survey_dashboard.set_lifecycle('LOADING')
        self.engine = cls(self.settings, self.mode.currentData(), self.queue_frame, self.bridge.status.emit)
        if cls is SurveyEngine:
            self.engine.environment_label = getattr(self, "environment_label", "실측 환경 미확인")
        self.thread = threading.Thread(target=self.engine.run, daemon=True, name="D4D-Inference")
        self.mode.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.start_button.setObjectName("stop")
        self.start_button.setText("■  중지")
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.thread.start()

    def queue_frame(self, frame):
        with self.frame_lock:
            self.pending = frame

    def on_status(self, status):
        state = status["state"]
        message = status["message"]
        if self.mode.currentData() == 'survey':
            self.survey_dashboard.set_lifecycle(state, message)
        if state == "READY":
            self.backend_label.setText(status["backend"].upper())
        elif state == "LOADING":
            self.badge.set_status('INITIALIZING', 'STARTING')
            self.assessment.setText("모델 준비 중")
            self.assessment_note.setText("추론 장치를 초기화하고 있습니다.")
        elif state in ("STOPPED", "ERROR"):
            with self.frame_lock:
                self.pending = None
            self.current_state = state
            self.last_seen = 0
            self.set_assessment(state, 0)
            self.badge.set_status(state, state, '#ffad85' if state == 'ERROR' else '#8da4b1')
            self.snapshot_button.setEnabled(False)
            self.survey_save.setEnabled(False)
            self.survey_panel.phase.setText("관측 오류 · 기록 보존" if state == "ERROR" else "관측 중지 · 마지막 분석 기록 / 현재 상태 미확인")
            self.health.setText(message)
            self.assessment_note.setText(message if state == "ERROR" else "수신 중지 · 마지막 분석 화면을 보존합니다.")
        elif state == "SAVED":
            self.snapshot_button.setEnabled(True)
        self.add_event(state, message)

    def set_assessment(self, state, score):
        replay = self.mode.currentData() == "replay"
        mapping = {
            "IDLE": ("대기 중", "수신을 시작해 대상 대역을 관측하세요.", "#dce5e9"),
            "CLEAR": ("탐지 신호 없음", "현재 분석 프레임에 기준 이상의 드론 박스가 없습니다.", "#91e7cc"),
            "CANDIDATE": ("드론 신호 후보", "단일 프레임 검출 · 다음 관측에서 재확인합니다.", "#e4cf8b"),
            "DETECTED": ("드론 신호 탐지", "최근 관측에서 드론 패턴이 반복 검출되었습니다.", "#ffab83"),
            "DEGRADED": ("수신 품질 확인", "초기 수신·오버런·데이터 지연으로 판정을 보류합니다.", "#e4cf8b"),
            "STALE": ("새 데이터 대기", "최신 IQ 프레임이 도착하지 않아 판정을 보류합니다.", "#e4cf8b"),
            "STOPPED": ("수신 중지", "마지막 분석 화면을 보존합니다.", "#81919a"),
            "ERROR": ("수신 오류", "장치 및 오류 기록을 확인하세요.", "#ffab83"),
        }
        text, note, color = mapping.get(state, mapping["IDLE"])
        self.assessment.setText(("[재생] " if replay else "") + text)
        self.assessment.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {color};")
        self.assessment_note.setText(note)
        self.model_score.setText(f"{score:.0%}" if state in ("CLEAR", "CANDIDATE", "DETECTED") else "—")

    def tick(self):
        self.clock_label.setText(datetime.now().strftime("%Y.%m.%d  %H:%M:%S") + "  LOCAL")
        running = bool(self.thread and self.thread.is_alive())
        for button, action in zip(self.page_buttons, self.mode_actions):
            button.setEnabled(not running)
            action.setEnabled(not running)
        self.settings_action.setEnabled(self.settings_button.isEnabled())
        self.run_action.setEnabled(self.start_button.isEnabled())
        self.save_action.setEnabled((self.survey_save if self.mode.currentData() == 'survey' else self.snapshot_button).isEnabled())
        if self.mode.currentData() == 'demo':
            return
        with self.frame_lock:
            frame, self.pending = self.pending, None
        if frame:
            self.render_frame(frame)
        if self.mode.currentData() == "survey":
            self.survey_panel.refresh_ages()
            self.survey_dashboard.refresh()
            _, _, color, tag = SURVEY_STATES[self.survey_dashboard.state]
            self.badge.set_status(tag, self.survey_dashboard.state, color)
            if isinstance(self.engine,SurveyEngine) and self.engine.session and self.last_dashboard_state != self.survey_dashboard.state:
                data=self.survey_dashboard.assessment
                entry=dict(utc=datetime.now().astimezone().isoformat(),host_mono=time.perf_counter(),
                    **{k:data[k] for k in ('state','active_regions','score','episodes','focus','focus_age','source_age','quality')})
                try:
                    with (self.engine.session/'dashboard_states.jsonl').open('a',encoding='utf-8') as log:
                        log.write(json.dumps(entry,ensure_ascii=False)+'\n')
                except OSError as exc:
                    self.health.setText(f'대시보드 상태 기록 실패: {exc}')
                focus = data['focus']
                frequency = f"{focus['low_mhz']:.1f}–{focus['high_mhz']:.1f} MHz" if focus else '유효 주파수 근거 없음'
                self.add_event('SURVEY / ' + data['state'], SURVEY_STATES[data['state']][0] + ' · ' + frequency)
                self.last_dashboard_state = self.survey_dashboard.state
        if self.thread and not self.thread.is_alive():
            self.thread = None
            self.start_button.setEnabled(True)
            self.start_button.setObjectName("primary")
            self.start_button.style().unpolish(self.start_button)
            self.start_button.style().polish(self.start_button)
            self.start_button.setText("▶  샘플 재생" if self.mode.currentData() == "replay" else "▶  수신 시작")
            self.mode.setEnabled(True)
            self.settings_button.setEnabled(True)
            self.survey_save.setEnabled(False)
            if self.closing:
                self.close()
        if self.thread and self.last_seen and self.mode.currentData() != "survey" and time.monotonic() - self.last_seen > 1.2:
            self.set_assessment("STALE", 0)
            self.badge.set_status('DATA STALE', 'STALE', '#e9ce85')
            self.snapshot_button.setEnabled(False)

    def render_frame(self, f):
        self.latest = f
        self.last_seen = time.monotonic()
        if f["mode"] == "survey":
            self.survey_dashboard.ingest(f)
            self.survey_panel.render(f)
            _, _, color, tag = SURVEY_STATES[self.survey_dashboard.state]
            self.badge.set_status(tag, self.survey_dashboard.state, color)
            self.metrics["band"][0].setText(str(f["total_records"]))
            if f["sweep"]:
                self.metrics["coverage"][0].setText(f"{f['sweep']['seconds']:.2f}")
                self.metrics["coverage"][1].setText(f"s · 사이클 {f['cycle']} · 후보 {len(f['sweep']['candidates'])}")
            if f["zoom"]:
                self.metrics["latency"][0].setText(f"{f['zoom']['inference_ms']:.1f}")
                self.metrics["latency"][1].setText(f"ms · 최근 IQ 중심 {f['zoom']['center_mhz']:.1f} MHz")
            self.health.setText(f"SWEEP + IQ · overrun {f['runtime_overruns']} / host drop {f['host_drops']} · LNA/VGA {self.settings.lna}/{self.settings.vga} · 미검사 구간 탐색 {f['next_explore_mhz']:.1f} MHz")
            self.session_label.setText(f"{f['elapsed']:.0f} s  /  {f['visits']} visits  /  {f['processed']} frames")
            self.survey_save.setEnabled(True)
            return
        self.current_state = f["state"]
        replay = f["mode"] == "replay"
        self.badge.set_status('REPLAY' if replay else 'LIVE / FIXED', 'REPLAY' if replay else 'SCANNING', '#91c5c0')
        self.metrics["latency"][0].setText(f"{f['inference_ms']:.1f}")
        self.metrics["latency"][1].setText(f"ms · 프레임 처리 지연 {f['age_ms']:.0f} ms")
        self.metrics["coverage"][0].setText(f"{f['fps']:.1f}")
        coverage = f"분석 비율 {f['coverage_pct']:.1f}%" if not replay else "녹화 이미지 · RF 실시간 수신 아님"
        self.metrics["coverage"][1].setText(f"fps · {coverage}")
        self.spectrum.set_data(f["spectrum"])
        self.waterfall.set_data(f["spectrum"])
        self.model_image.set_data(f["image"], f["boxes"])
        self.set_assessment(f["state"], f["confidence"])
        if not replay:
            self.signal_label.setText(f"IQ {f['signal']['rms_dbfs']:.1f} dBFS  /  CLIP {f['signal']['clipped_pct']:.2f}%")
        else:
            self.signal_label.setText("REPLAY · RF 측정 없음")
        targets = [b for b in f["boxes"] if b["in_target"]]
        if targets and not replay:
            best = max(targets, key=lambda b: b["confidence"])
            self.box_detail.setText(f"{best['low_mhz']:.2f}–{best['high_mhz']:.2f} MHz · {best['bandwidth_mhz']:.2f} MHz\n모델 점수 {best['confidence']:.3f} · 기준 {self.settings.confidence:.2f}")
        else:
            self.box_detail.setText(f"model_02a_picked.pt · 기준 {self.settings.confidence:.2f}\n" + ("녹화 원본의 주파수 좌표는 표시하지 않습니다." if replay else
                f"고정 채널 조건: 폭 7–13 MHz / IoU ≥ 0.60\n조건 불일치 {f['rejected_drone_boxes']}개 · 원본 drone 점수 {f['raw_drone_score']:.2f}"))
        stats = f["radio"]
        if replay:
            self.health.setText(f"REPLAY  ·  {f['sample']}")
        else:
            overruns = "확인 중" if stats["overruns"] is None else str(stats["overruns"])
            self.health.setText(f"RX {stats['mbps']:.1f} MB/s  ·  USB overrun {overruns}  ·  분석 생략 {f['skipped']:,} frames  ·  LNA/VGA {self.settings.lna}/{self.settings.vga} dB")
        self.pipeline_label.setText(f"전처리 {f['dsp_ms']:.1f} ms  →  추론 {f['inference_ms']:.1f} ms  ·  20 ms / 640 × 640  ·  AMP / Bias-T OFF")
        elapsed = int(f["elapsed"])
        self.session_label.setText(f"SESSION {elapsed // 60:02d}:{elapsed % 60:02d}   /   {f['processed']:,} analyzed   /   {f['events']} events")
        self.snapshot_button.setEnabled(True)
        if f["state"] != self.last_event_state:
            if f["state"] in ("DETECTED", "CLEAR", "DEGRADED"):
                self.add_event(("REPLAY / " if replay else "") + f["state"], f"drone score {f['confidence']:.3f} · frame {f['sequence']:,} · {f['backend']}")
            self.last_event_state = f["state"]

    def add_event(self, kind, message):
        compact = message.replace("\n", " ")
        row = QTreeWidgetItem([f'{datetime.now():%H:%M:%S}', kind, compact])
        row.setToolTip(2, message)
        position = self.log_table.verticalScrollBar().value()
        self.log_table.insertTopLevelItem(0, row)
        if self.log_table.topLevelItemCount() > 500:
            self.log_table.takeTopLevelItem(500)
        self.log_table.verticalScrollBar().setValue(position + 1 if position else 0)

    def snapshot(self):
        if self.engine and self.thread:
            self.snapshot_button.setEnabled(False)
            self.survey_save.setEnabled(False)
            self.engine.request_snapshot()
            self.add_event("CAPTURE", "다음 분석 프레임과 주파수·품질 근거를 저장합니다. 수신 모드에서는 IQ를 함께 저장합니다.")

    def open_output(self):
        path = self.engine.session if self.engine and self.engine.session else ROOT / "output"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def reset_layout(self):
        self.inspector_action.setChecked(True)
        self.records_action.setChecked(True)
        self.inspector_stack.show()
        self.drawer.show()
        self.workspace_splitter.setSizes([max(690, self.width() - 354), 350])
        self.analysis_splitter.setSizes([max(350, self.height() - 385), 235])
        self.fixed_views.setSizes([580, 390])
        self.fixed_scopes.setSizes([240, 220])
        self.survey_panel.views.setSizes([600, 440])
        self.survey_panel.scopes.setSizes([260, 160])

    def restore_layout(self):
        try:
            data=json.loads((ROOT/'runtime/ui_layout.json').read_text(encoding='utf-8'))
            if not isinstance(data,dict):
                return
            for key, widget in [('workspace',self.workspace_splitter),('analysis',self.analysis_splitter),
                                ('survey',self.survey_panel.views),('fixed',self.fixed_views)]:
                sizes=data.get(key)
                if isinstance(sizes,list) and len(sizes)==2 and all(isinstance(v,int) and 0<v<10000 for v in sizes):
                    widget.setSizes(sizes)
            for key, control, widget in [('inspector',self.inspector_action,self.inspector_stack),
                                         ('records',self.records_action,self.drawer)]:
                visible=data.get(key,True)
                if isinstance(visible,bool):
                    control.setChecked(visible)
                    widget.setVisible(visible)
        except (OSError,ValueError,TypeError):
            pass

    def save_layout(self):
        if not self.persist_layout:
            return
        data=dict(workspace=self.workspace_splitter.sizes(),analysis=self.analysis_splitter.sizes(),
                  survey=self.survey_panel.views.sizes(),fixed=self.fixed_views.sizes(),
                  inspector=self.inspector_action.isChecked(),records=self.records_action.isChecked())
        try:
            path=ROOT/'runtime/ui_layout.json'
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(data,indent=2),encoding='utf-8')
        except OSError:
            pass

    def closeEvent(self, event):
        self.nu87_indicator.close()
        if self.thread and self.thread.is_alive():
            self.closing = True
            self.engine.stop()
            self.start_button.setEnabled(False)
            self.start_button.setText("종료 중…")
            event.ignore()
        else:
            self.demo_panel.deactivate()
            self.save_layout()
            event.accept()
