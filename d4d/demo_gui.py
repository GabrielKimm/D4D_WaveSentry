"""Synthetic demo workspace, isolated from the actual receive/inference engines."""
from datetime import datetime
from math import sin
from PySide6.QtCore import Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QToolButton, QSplitter, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QLineEdit, QDialog, QFormLayout, QComboBox, QCheckBox, QDialogButtonBox)
from .demo_model import DemoModel, SCENES, TRACK_IDS, threat, degree, course_text
from .satellite_map import SatelliteMap
from .ui_theme import panel, ElidedLabel


def label(text, role='muted'):
    widget=QLabel(text)
    widget.setObjectName(role)
    widget.setWordWrap(True)
    return widget


class DemoEvidence(QWidget):
    """A visibly synthetic RF illustration; never presented as received IQ."""
    def __init__(self, model):
        super().__init__()
        self.model=model
        self.track_id='H-01'
        self.setMinimumHeight(250)
        self.setMaximumHeight(370)
        self.setAccessibleName('RF 입력과 검출 박스')

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w=self.width()
        t=self.model.observed_time
        tracks=self.model.tracks()
        d=next((d for d in tracks if d['id']==self.track_id),tracks[0])
        for row in range(2):
            score=d['score'] if row==0 else self.model.tracks()[0]['score']
            y=24+row*105
            p.fillRect(QRectF(0,y,w,84),QColor('#151a1c'))
            for xx in range(0,w,6):
                for yy in range(0,84,6):
                    value=int(32+19*(sin(xx*1.7+yy*2.1+t*.4)+1))
                    if (xx+int(t*3)+row*19)%68<26:
                        value+=50
                    p.fillRect(QRectF(xx,y+yy,5,5),QColor(value,value+3,value+3))
            p.setPen(QPen(QColor('#a2c9bb'),1))
            p.drawRect(QRectF(4,y+17,w-9,59))
            p.fillRect(QRectF(4,y+17,100,16),QColor('#a2c9bb'))
            p.setFont(QFont('Consolas',8));p.setPen(QColor('#14251e'))
            p.drawText(8,y+29,f"DRONE {score:.2f}")
            p.setPen(QColor('#9aacae'))
            p.drawText(0,y-8,f"{d['id']} / {d['freq']:.2f} GHz" if row==0 else 'F-01 / 2.44 GHz')
        p.setPen(QColor('#8a9b9f'))
        p.drawText(0,239,'RF / CLASSIFICATION')
        p.end()


class DemoSettings(QDialog):
    def __init__(self, demo, parent):
        super().__init__(parent)
        self.setWindowTitle('관측 설정')
        self.setMinimumWidth(420)
        layout=QVBoxLayout(self)
        layout.addWidget(label('관측 상태', 'title'))
        form=QFormLayout()
        self.mode=QComboBox()
        for title,value in [('위치 추적','position'),('H-01 방향만 수신','bearing'),('수신 연결 끊김','lost')]:
            self.mode.addItem(title,value)
        self.mode.setCurrentIndex(self.mode.findData(demo.model.mode))
        form.addRow('관측 상태',self.mode)
        self.trails=QCheckBox('최근 60초 궤적')
        self.trails.setChecked(demo.map.trails)
        self.error=QCheckBox('선택 기체 위치 오차')
        self.error.setChecked(demo.map.uncertainty)
        self.details=QCheckBox('모든 기체에 거리·방위 표시')
        self.details.setChecked(demo.map.all_labels)
        for box in [self.trails,self.error,self.details]:
            form.addRow(box)
        layout.addLayout(form)
        layout.addWidget(label('방향만 수신할 때 H-01의 위치·거리·속도·진행 방향은 표시하지 않습니다.\n지도와 RF/ML, 해독·피아 정보는 모두 시나리오 입력입니다.'))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DemoPanel(QWidget):
    state_changed=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.model=DemoModel()
        self.selected='F-01'
        self.active=False
        self.acked=False
        self.previous_threat=None
        self.last_ui_state=None
        self.frames=0
        self.current_tracks=[]
        root=QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0);root.setSpacing(4)
        self.views=QSplitter(Qt.Horizontal)
        self.views.setChildrenCollapsible(False)
        self.rf_toggle=QToolButton();self.rf_toggle.setText('RF 근거');self.rf_toggle.setCheckable(True);self.rf_toggle.setChecked(False)
        self.rf_toggle.setToolTip('RF 근거 패널 표시')
        map_frame,body=panel('상황 지도 / TRACK MAP',self.rf_toggle)
        body.setContentsMargins(0,0,0,0);body.setSpacing(0)
        self.map=SatelliteMap(self.model)
        self.map.track_id=self.selected
        self.map.selected.connect(self.select)
        body.addWidget(self.map,1)
        self.map_footer=ElidedLabel('RX-A / 고정 어레이     N-UP · 궤적 60 s · 진행 벡터 20 s')
        self.map_footer.setContentsMargins(10,5,10,5)
        body.addWidget(self.map_footer)
        self.views.addWidget(map_frame)
        self.rf_panel,rf=panel('모델 입력 / 검출 박스',label('RF / ML','eyebrow'))
        self.rf_panel.setMinimumWidth(205);self.rf_panel.setMaximumWidth(300)
        self.evidence=DemoEvidence(self.model);rf.addWidget(self.evidence)
        rf.addWidget(label('최근 유효 RF / 형태 분류','eyebrow'))
        self.rf_detail=label('');rf.addWidget(self.rf_detail)
        rf.addWidget(label('RF 탐지 → 형태 분류 → ID 확인\n해독 결과는 시나리오 입력입니다.'))
        rf.addStretch()
        self.views.addWidget(self.rf_panel)
        self.views.setStretchFactor(0,1)
        self.views.setSizes([760,240])
        self.rf_toggle.toggled.connect(self.rf_panel.setVisible)
        self.rf_panel.hide()
        root.addWidget(self.views)
        self._build_records()
        self._build_inspector()
        self.timer=QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)

    def _build_records(self):
        self.records=QWidget()
        col=QVBoxLayout(self.records);col.setContentsMargins(10,7,10,5);col.setSpacing(4)
        row=QHBoxLayout()
        self.counts=label('아군 2 · 적군 0 · 미식별 1', 'eyebrow');self.counts.setWordWrap(False)
        row.addWidget(self.counts);row.addStretch()
        self.search=QLineEdit();self.search.setPlaceholderText('기체 / 피아 검색');self.search.setMaximumWidth(240)
        self.search.setAccessibleName('기체 검색')
        self.search.textChanged.connect(self.filter_rows);row.addWidget(self.search);col.addLayout(row)
        self.table=QTreeWidget();self.table.setRootIsDecorated(False);self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setStyleSheet('QTreeWidget::item { padding:2px 6px; }')
        self.table.setColumnCount(7)
        self.table.setHeaderLabels(['기체 / 피아','어레이 거리','속도','진행 · COG','방위 · BRG','RF / ML','관측 상태'])
        self.table.header().setSectionResizeMode(QHeaderView.Stretch)
        self.rows={}
        for ident in TRACK_IDS:
            item=QTreeWidgetItem(['']*7);item.setData(0,Qt.UserRole,ident)
            self.rows[ident]=item;self.table.addTopLevelItem(item)
        self.table.currentItemChanged.connect(lambda item,old:self.select(item.data(0,Qt.UserRole)) if item else None)
        col.addWidget(self.table,1)
        col.addWidget(label('속도 m/s · COG 이동 방향 · BRG 어레이에서 본 방위'))
        self.events_panel=QWidget();events=QVBoxLayout(self.events_panel);events.setContentsMargins(10,7,10,5)
        events.addWidget(label('EVENTS · 현지 시각 / 최근 18건','eyebrow'))
        self.events=QTreeWidget();self.events.setRootIsDecorated(False);self.events.setAlternatingRowColors(True)
        self.events.setHeaderLabels(['시각','유형','관측 내용'])
        self.events.setColumnWidth(0,94);self.events.setColumnWidth(1,130)
        self.events.header().setStretchLastSection(True);events.addWidget(self.events)

    def _build_inspector(self):
        self.inspector=QWidget();col=QVBoxLayout(self.inspector);col.setContentsMargins(0,0,0,0);col.setSpacing(5)
        frame,body=panel('탐지 판정 / INSPECTOR',label('TRACK','eyebrow'))
        self.alert_title=label('보호구역 접근','title');body.addWidget(self.alert_title)
        self.alert_note=label('시나리오 지정 기체의 위치와 이동을 추적합니다.');body.addWidget(self.alert_note)
        self.identity=label('H-01   적군');self.identity.setMinimumHeight(36);body.addWidget(self.identity)
        grid=QGridLayout();grid.setHorizontalSpacing(15);grid.setVerticalSpacing(6)
        self.values={}
        for i,(key,title) in enumerate([('distance','어레이 기준 거리'),('bearing','어레이 기준 방위 · BRG'),('speed','이동 속도'),('course','진행 방향 · COG')]):
            r,c=divmod(i,2)
            grid.addWidget(label(title),r*2,c)
            value=label('—','metric');value.setStyleSheet("font: 24px 'Consolas'; color:#e1e6e6;")
            self.values[key]=value;grid.addWidget(value,r*2+1,c)
        body.addLayout(grid)
        body.addWidget(label('COG 북쪽 0° · BRG 어레이 기준 방위각'))
        self.accuracy=label('');body.addWidget(self.accuracy)
        body.addSpacing(12)
        body.addWidget(label('최근 유효 RF / 형태 분류','eyebrow'))
        self.ml=label('');body.addWidget(self.ml)
        body.addSpacing(12)
        body.addWidget(label('해독 / 피아 판정 근거','eyebrow'))
        self.basis=label('');body.addWidget(self.basis)
        body.addSpacing(12)
        body.addWidget(label('관측 품질 / 해석 범위','eyebrow'))
        body.addWidget(label('ML 점수와 피아 판정은 구분합니다.'))
        body.addStretch()
        self.ack=QPushButton('접근 경보 확인');self.ack.clicked.connect(self.acknowledge);body.addWidget(self.ack)
        body.addWidget(label('확인 후에도 기체·궤적 표시 유지'))
        col.addWidget(frame,1)

    def add_event(self,kind,text):
        self.events.insertTopLevelItem(0,QTreeWidgetItem([datetime.now().strftime('%H:%M:%S'),kind,text]))
        while self.events.topLevelItemCount()>18:
            self.events.takeTopLevelItem(18)

    def activate(self):
        self.active=True
        self.model.set_mode('position')
        self.model.set_running(True)
        self._restart_scenario()
        self.map.set_active(True)
        self.add_event('RX','수신 시작 · '+SCENES[self.model.site].title)
        self.timer.start();self.refresh()

    def deactivate(self):
        self.active=False
        self.map.set_active(False)
        self.model.set_running(False)
        self.timer.stop()

    def toggle(self):
        self.model.set_running(not self.model.running)
        self.add_event('RX','수신 시작' if self.model.running else '수신 중지 · 마지막 위치 보존')
        self.refresh()

    def set_site(self,site):
        if site not in SCENES or site==self.model.site:
            return
        self.model.site=site
        # Selecting a new site starts a fresh observation context, never a stale fix
        # at coordinates that belonged to a different fictional receiver.
        self.model.set_mode('position')
        self.model.set_running(self.active)
        self._restart_scenario()
        self.add_event('SITE',SCENES[site].title+' · 관측 지역 전환')
        self.refresh()

    def select(self,ident):
        if ident not in {d['id'] for d in self.model.tracks()}:
            return
        self.selected=self.map.track_id=self.evidence.track_id=ident
        self.table.blockSignals(True);self.table.setCurrentItem(self.rows[ident]);self.table.blockSignals(False)
        self.refresh(False)

    def filter_rows(self):
        query=self.search.text().strip().casefold()
        active={d['id'] for d in self.model.tracks()}
        blocked=self.table.blockSignals(True)
        for ident,item in self.rows.items():
            item.setHidden(ident not in active or query not in item.text(0).casefold())
        self.table.blockSignals(blocked)

    def _scene_ready(self):
        return self.model.site!='airbase' or self.map.tile_ready or self.map.disabled or self.map.failed or self.map.user_schematic

    def _restart_scenario(self):
        self.model.reset_scenario(ready=self._scene_ready())
        self.selected=self.map.track_id=self.evidence.track_id='F-01'
        self.previous_threat=None;self.acked=False

    def acknowledge(self):
        self.acked=True
        self.add_event('ACK',self.alert_track+' 경보 확인 · 추적 유지')
        self.refresh(False)

    def open_settings(self):
        dialog=DemoSettings(self,self.window())
        if dialog.exec()==QDialog.Accepted:
            self.model.set_mode(dialog.mode.currentData())
            self.map.trails=dialog.trails.isChecked();self.map.uncertainty=dialog.error.isChecked();self.map.all_labels=dialog.details.isChecked()
            self.previous_threat=None;self.acked=False
            self.add_event('OBSERVATION',dialog.mode.currentText())
            self.refresh()

    def refresh(self,advance=True):
        if self.active and self._scene_ready():
            self.model.set_scene_ready()
        if advance:
            self.model.advance()
        tracks=self.model.tracks();self.current_tracks=tracks
        active={d['id'] for d in tracks}
        for event in self.model.take_events():
            spotted=event['kind']=='spot'
            self.add_event('CONTACT' if spotted else 'TRACK LOST',event['id']+(' · 적군 기체 포착' if spotted else ' · 추적 신호 소실'))
            if spotted and event['id'] in active:
                self.selected=event['id'];self.acked=False
        hostiles=[d for d in tracks if d['affiliation']=='적군']
        if self.selected not in active:
            self.selected=hostiles[-1]['id'] if hostiles else 'F-01'
        self.map.track_id=self.evidence.track_id=self.selected
        hostile=next((d for d in hostiles if d['id']==self.selected),hostiles[0] if hostiles else None)
        self.alert_track=hostile['id'] if hostile else ''
        key,title=threat(hostile,self.model.site) if hostile else ('clear','주변 감시 중')
        stale=self.model.stale
        if stale:
            title='수신 연결 끊김' if self.model.mode=='lost' else '수신 중지'
        elif hostile and self.model.bearing_only(hostile):
            key,title='bearing','방향만 수신'
        if not stale and key!=self.previous_threat:
            if self.previous_threat is not None:
                kind='ZONE ENTER' if key=='inside' else 'ZONE EXIT' if self.previous_threat=='inside' else 'TRACK'
                self.add_event(kind,title+(' · '+self.alert_track if hostile else ''))
            self.previous_threat=key;self.acked=False
        self.alert_title.setText(title)
        alert_style='font-size:22px;font-weight:600;color:'+('#a5b1b7' if stale else '#efb093' if hostile else '#a4dcc8')+';'
        if self.alert_title.styleSheet()!=alert_style:
            self.alert_title.setStyleSheet(alert_style)
        self.alert_note.setText('마지막 관측 정보입니다. 현재 이동 상태는 알 수 없습니다.' if stale else
            '방위만 수신 중입니다. 위치·거리·이동 상태는 미확정입니다.' if key=='bearing' else
            f'적군 {len(hostiles)}대 · 위치와 이동 방향을 추적합니다.' if hostiles else
            '고정 어레이에서 주변 기체의 RF 신호를 감시합니다.')
        self.counts.setText(f'아군 2 · 적군 {len(hostiles)} · 미식별 1')
        map_source='개략 지도 · 위성영상 아님' if self.map.failed or self.map.user_schematic or self.map.disabled else '공개 위성영상' if self.map.tile_ready else '위성영상 연결 중'
        self.map_footer.setText('대구 11전비 주변 · '+map_source if self.model.site=='airbase' else
            SCENES[self.model.site].array+' / 고정 어레이 · 개략 지도     N-UP · 궤적 60 s · 진행 벡터 20 s')
        for d in tracks:
            bearing=self.model.bearing_only(d)
            status='LAST' if stale else '방향 추적' if bearing else '순찰 중' if d['affiliation']=='아군' else ('구역 진입' if threat(d,self.model.site)[0]=='inside' else '접근 중' if d['radial']<0 else '이탈 중') if d['affiliation']=='적군' else '추적 중'
            fields=[f"{d['id']}  {d['affiliation']}",'—' if bearing else f"{d['distance']:.0f} m",
                    '—' if stale or bearing else f"{d['speed']:.1f} m/s",'—' if stale or bearing else course_text(d['course']),
                    degree(d['bearing']),f"{d['freq']:.2f} GHz / {d['score']:.2f}",status]
            for column,value in enumerate(fields):
                self.rows[d['id']].setText(column,value)
            self.rows[d['id']].setForeground(0,QColor('#9babb1' if stale else d['color']))
            self.rows[d['id']].setToolTip(4,'어레이 → 기체 방위각 · 이동 진행 방향과 다릅니다.')
        self.filter_rows()
        d=next(d for d in tracks if d['id']==self.selected)
        bearing=self.model.bearing_only(d)
        self.table.blockSignals(True)
        if self.table.currentItem()!=self.rows[self.selected]:
            self.table.setCurrentItem(self.rows[self.selected])
        self.table.blockSignals(False)
        stamp=f'LAST · {self.model.age:.0f}초 전' if stale else 'LIVE · 연속 갱신'
        self.identity.setText(f"{d['id']}   {d['affiliation']}   /   {stamp}")
        self.values['distance'].setText('—' if bearing else f"{d['distance']:.0f} m")
        self.values['bearing'].setText(degree(d['bearing']))
        self.values['speed'].setText('—' if stale or bearing else f"{d['speed']:.1f} m/s")
        self.values['course'].setText('—' if stale or bearing else course_text(d['course']))
        self.accuracy.setText('방향 정보만 유효 · 위치·거리 미확정' if bearing else f"{'마지막 관측 위치' if stale else '관측 위치'} · 오차 ±{SCENES[self.model.site].error:g} m")
        self.ml.setText(f"RF 탐지       {d['freq']:.2f} GHz · 20 MHz\nML 분류       drone · {d['score']:.2f}")
        self.basis.setText('해독 상태     '+('식별 보류' if d['id']=='U-01' else 'ID 수신 가정')+'\n피아 근거     '+d['basis'])
        self.rf_detail.setText(f"{d['id']} · {d['freq']:.2f} GHz\ndrone · {d['score']:.2f}"+('\nLAST · 갱신 중단' if stale else ''))
        self.ack.setText('경보 확인됨 · 추적 유지' if self.acked else '접근 경보 확인')
        self.ack.setEnabled(bool(hostile) and not self.acked and not stale)
        self.map.update()
        self.frames+=1
        if self.frames%4==0:
            self.evidence.update()
        current=(self.model.running,self.model.mode,self.model.site)
        if current!=self.last_ui_state:
            self.last_ui_state=current;self.state_changed.emit()
