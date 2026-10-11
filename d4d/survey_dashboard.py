"""Evidence-aware assessment inspector for the RF workstation."""
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QProgressBar
from .survey_assessment import SurveyAssessment
from .status_tag import StatusTag


STATES = {
    'IDLE': ('분석 대기', '수신을 시작하면 주변 RF 신호의 드론 유사 형태를 분석합니다.', '#8da4b1', 'STANDBY'),
    'STARTING': ('드론 신호 분석 준비', '수신·모델 초기화 후 첫 IQ 분석 결과를 기다리고 있습니다.', '#8da4b1', 'PREPARING'),
    'DETECTED': ('드론 의심 신호 탐지', '최근 6초 내 반복 근거가 누산 기준을 충족했습니다.', '#ffad85', 'DETECTED'),
    'CANDIDATE': ('드론 후보 분석 중', '드론 유사 패턴을 재확인하고 있습니다. 반복 근거는 아직 부족합니다.', '#e9ce85', 'ANALYZING'),
    'NO_EVIDENCE': ('현재 탐지 근거 없음', '현재 관측에서 반복 기준 미충족 · 주변 드론이 없다는 뜻은 아닙니다.', '#91c5c0', 'SCANNING'),
    'GAP': ('최근 탐지 · 재확인 필요', '마지막 탐지 근거가 오래됐습니다. 현재 존재 여부는 미확인입니다.', '#b1afc6', 'RECHECK'),
    'QUALITY': ('입력 품질 문제 · 판정 보류', '수신 품질이 회복될 때까지 현재 탐지 판정을 보류합니다.', '#e9ce85', 'QUALITY HOLD'),
    'STALE': ('관측 지연 · 판정 보류', '새 분석 데이터가 도착하지 않습니다. 마지막 결과를 현재 탐지로 표시하지 않습니다.', '#e9ce85', 'DATA STALE'),
    'STOPPING': ('분석 중지 중', '수신을 정리하고 있습니다. 현재 탐지 판정은 중단됐습니다.', '#8da4b1', 'STOPPING'),
    'STOPPED': ('분석 중지 · 현재 미확인', '지난 분석 기록은 보존됩니다. 수신을 시작하면 새로 분석합니다.', '#8da4b1', 'STOPPED'),
    'ERROR': ('수신 오류 · 판정 보류', '장치 연결과 아래 오류 기록을 확인하세요.', '#ffad85', 'ERROR'),
}


def text_label(text='', size=12, color='#999ea7', bold=False):
    label=QLabel(text)
    label.setStyleSheet(f'background:transparent; border:0; color:{color}; font-size:{size}px; font-weight:{600 if bold else 400};')
    return label


class SurveyDashboard(QFrame):
    def __init__(self):
        super().__init__()
        self.model=SurveyAssessment()
        self.state='IDLE'
        self.next_refresh=0
        self.setObjectName('surveyDashboard')
        layout=QVBoxLayout(self)
        layout.setContentsMargins(14,12,14,12)
        layout.setSpacing(10)
        top=QHBoxLayout()
        top.addWidget(text_label('탐지 판정 / INSPECTOR',11,'#c2c5ca',True))
        top.addStretch()
        self.tag=StatusTag()
        top.addWidget(self.tag)
        layout.addLayout(top)
        self.headline=text_label('',21,'#e9a88b',True)
        self.headline.setWordWrap(True)
        self.description=text_label('',11,'#b4b7be')
        self.description.setWordWrap(True)
        self.last_detection=text_label('',11)
        layout.addSpacing(5)
        layout.addWidget(self.headline)
        layout.addWidget(self.description)
        layout.addWidget(self.last_detection)
        def divider():
            line=QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet('background:#3b3d42; border:0;')
            layout.addWidget(line)
        divider()
        self.values={}
        layout.addWidget(text_label('최근 유효 주파수',11,'#aeb2ba',True))
        frequency=text_label('—',21,'#e0e2e6',True)
        frequency.setStyleSheet("color:#e0e2e6; font:20px 'Consolas'; background:transparent;")
        frequency_note=text_label('유효 근거 대기',11)
        layout.addWidget(frequency)
        layout.addWidget(frequency_note)
        self.values['frequency']=(frequency,frequency_note)
        divider()
        row=QHBoxLayout()
        for key,title,caption in [('regions','탐지 RF 영역','영역 수 · 드론 대수 아님'),
                                  ('score','누산 근거','점수 · 확률 아님')]:
            col=QVBoxLayout()
            col.setSpacing(5)
            col.addWidget(text_label(title,11,'#aeb2ba',True))
            value=text_label('—',23,'#e0e2e6',True)
            note=text_label(caption,10)
            note.setWordWrap(True)
            col.addWidget(value)
            col.addWidget(note)
            row.addLayout(col,1)
            self.values[key]=(value,note)
        layout.addLayout(row)
        self.meter=QProgressBar()
        self.meter.setRange(0,400)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(4)
        layout.addWidget(self.meter)
        divider()
        layout.addWidget(text_label('대역별 최근 관측',11,'#aeb2ba',True))
        self.bands=text_label('',11)
        self.bands.setWordWrap(True)
        layout.addWidget(self.bands)
        divider()
        layout.addWidget(text_label('관측 품질 / 해석 범위',11,'#aeb2ba',True))
        limits=text_label('RF 형태를 근거로 한 의심 탐지입니다.\n기체·기종 또는 송신기 식별 결과가 아닙니다.\n대역은 순차 관측하며 관측 공백이 있습니다.',11)
        limits.setWordWrap(True)
        layout.addWidget(limits)
        self.telemetry=text_label('',11)
        layout.addWidget(self.telemetry)
        self.refresh(force=True)

    def reset(self,ranges):
        self.model.reset(ranges)
        self.refresh(force=True)

    def set_lifecycle(self,state,message=''):
        self.model.set_lifecycle(state,message)
        self.refresh(force=True)

    def ingest(self,frame):
        self.model.ingest(frame)
        self.refresh(force=True)

    def refresh(self,now=None,force=False):
        now=time.perf_counter() if now is None else now
        if not force and now<self.next_refresh:
            return
        self.next_refresh=now+.2
        data=self.model.evaluate(now)
        self.assessment=data
        title,description,color,tag=STATES[data['state']]
        self.state=data['state']
        self.setStyleSheet(f'QFrame#surveyDashboard {{background:#252629; border:0; border-top:2px solid {color};}}')
        self.headline.setText(title)
        self.headline.setStyleSheet(f'background:transparent; border:0; font-size:21px; font-weight:600; color:{color};')
        self.tag.set_status(tag, self.state, color)
        self.description.setText(description)
        age=data['last_detection_age']
        self.last_detection.setText('이번 세션 누산 탐지 기록 없음' if age is None else f'마지막 누산 탐지 근거  {age:.1f}초 전')
        self.values['regions'][0].setText('—' if data['active_regions'] is None else str(data['active_regions']))
        focus=data['focus']
        self.values['frequency'][0].setText(f"{focus['low_mhz']:.1f}–{focus['high_mhz']:.1f}" if focus else '—')
        self.values['frequency'][1].setText(f"MHz · 근거 {data['focus_age']:.1f}초 전" if focus else '유효 근거 대기')
        score=data['score']
        self.values['score'][0].setText(f'{score:.2f}' if score is not None else '—')
        self.values['score'][1].setText(f"{data['episodes']}회차 · 진입 1.60점 / 3회차" if score is not None else '누산 전 · 확률 아님')
        self.meter.setValue(round(min(4,score or 0)*100))
        self.meter.setStyleSheet(f'QProgressBar {{border:0;background:#404349;}} QProgressBar::chunk {{background:{color};}}')
        labels={'DETECTED':'의심 신호 탐지','CANDIDATE':'후보 재확인','WAITING':'IQ 관측 대기',
                'NO_EVIDENCE':'탐지 근거 없음','HELD':'현재 판정 보류','QUALITY':'입력 품질 확인'}
        parts=[]
        for band in data['bands']:
            a,b=band['span']
            name='2.4 GHz' if (a,b)==(2400,2500) else '5 GHz' if (a,b)==(5150,5890) else f'{a}–{b} MHz'
            age=f" · IQ {band['age']:.1f}초 전" if band['age'] is not None else ''
            parts.append(f"{name}   {labels[band['state']]}{age}")
        self.bands.setText('\n\n'.join(parts))
        sweep=data['sweep_seconds']
        self.telemetry.setText(f"{data['processed']} frames · sweep {sweep:.2f}s" if sweep is not None else '수신 대기')
        self.setAccessibleName('주변 드론 분석: '+title)
        self.setToolTip('현재 상태는 최근 관측 근거에 대한 판정입니다. 관측 공백 동안의 기체 존재·부재를 확정하지 않습니다.')
