"""Cesium/Esri imagery in the desktop demo, with an explicit native fallback."""
import json
import os
from pathlib import Path
from PySide6.QtCore import QObject, Qt, QUrl, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QLabel, QPushButton
from .demo_map import DemoMap
from .demo_model import SCENES, TRACK_IDS, SPOT_DURATION


ASSETS=Path(__file__).resolve().parents[1]/'assets/satellite'
# Public airport reference point; not an actual receiver or military asset position.
DAEGU_CENTER=dict(latitude=35+53/60+39/3600,longitude=128+39/60+32/3600)


def map_payload(model,selected,options):
    """Only send observable fields to the browser; never send a bearing-only fix."""
    scene=SCENES[model.site]
    tracks=[]
    for d in model.tracks():
        bearing=model.bearing_only(d)
        tracks.append(dict(id=d['id'],affiliation=d['affiliation'],color=d['color'],
            x=None if bearing else d['x'],y=None if bearing else d['y'],
            vx=None if bearing or model.stale else d['vx'],vy=None if bearing or model.stale else d['vy'],
            speed=None if bearing or model.stale else d['speed'],course=None if bearing or model.stale else d['course'],
            distance=None if bearing else d['distance'],bearing=d['bearing'],bearingOnly=bearing,
            trail=[] if bearing or not options.get('trails',True) else [[h['x'],h['y']] for h in model.trail(d['id'])],
            frequency=d['freq'],score=d['score']))
    return dict(site=model.site,center=DAEGU_CENTER,selected=selected,tracks=tracks,
                stale=model.stale,age=model.age,mode=model.mode,time=model.observed_time,
                scenarioTime=model.scenario_time,spotPulses=model.spot_pulses(),spotDuration=SPOT_DURATION,
                radius=scene.radius,zone=scene.zone,error=scene.error,**options)


class MapBridge(QObject):
    telemetry=Signal(str)
    selection=Signal(str)
    status=Signal(str,str)

    @Slot(str)
    def selectTrack(self,ident):
        if ident in TRACK_IDS:
            self.selection.emit(ident)

    @Slot(str,str)
    def reportStatus(self,status,message):
        self.status.emit(status,message[:300])

    @Slot()
    def useSchematic(self):
        self.status.emit('schematic','사용자가 개략 지도를 선택했습니다.')


class SatelliteMap(QWidget):
    selected=Signal(str)
    status_changed=Signal(str)

    def __init__(self,model):
        super().__init__()
        self.model=model
        self.track_id='H-01'
        self.trails=True;self.uncertainty=True;self.all_labels=False
        self.web=None;self.web_ready=False;self.tile_ready=False
        self.active=False;self.failed=False;self.user_schematic=False
        self.diagnostics=[]
        self.disabled=os.environ.get('WAVESENTRY_DEMO_MAP')=='schematic'
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        self.notice=QWidget();row=QHBoxLayout(self.notice);row.setContentsMargins(9,4,9,4)
        self.notice_label=QLabel('개략 지도 · 위성영상 아님');row.addWidget(self.notice_label,1)
        self.retry=QPushButton('위성지도 다시 연결');self.retry.clicked.connect(self.retry_satellite);row.addWidget(self.retry)
        layout.addWidget(self.notice)
        self.stack=QStackedWidget();layout.addWidget(self.stack,1)
        self.native=DemoMap(model);self.native.selected.connect(self.selected)
        self.stack.addWidget(self.native)
        self.setMinimumSize(400,300)
        self.notice.hide()

    @property
    def label_boxes(self):
        return self.native.label_boxes

    def _ensure_web(self):
        if self.web or self.disabled:
            return
        if not (ASSETS / 'vendor/cesium/Cesium.js').is_file():
            self._status('error', 'Run python tools/vendor_cesium.py to install the satellite map assets.')
            return
        # Lazy imports keep actual LIVE/SURVEY startup independent of Chromium.
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
        from PySide6.QtWebChannel import QWebChannel
        from .map_assets import asset_origin
        self.asset_url=asset_origin()+'/index.html'
        owner=self
        class MapPage(QWebEnginePage):
            def javaScriptConsoleMessage(self,level,message,line,source):
                owner.diagnostics.append(dict(level=str(level),message=message,line=line))
                owner.diagnostics=owner.diagnostics[-30:]
            def acceptNavigationRequest(self,url,kind,is_main_frame):
                if not is_main_frame or url.toString().split('#')[0]==owner.asset_url:
                    return True
                return False
        self.web=QWebEngineView(self)
        self.web.setPage(MapPage(self.web))
        settings=self.web.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows,False)
        self.web.setContextMenuPolicy(Qt.NoContextMenu)
        self.web.setAccessibleName('대구 위성 상황지도 · Cesium / Esri')
        self.channel=QWebChannel(self.web.page())
        self.bridge=MapBridge(self)
        self.bridge.selection.connect(self.selected)
        self.bridge.status.connect(self._status)
        self.channel.registerObject('mapBridge',self.bridge)
        self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._loaded)
        self.stack.addWidget(self.web)
        self.web.setUrl(QUrl(self.asset_url))
        self.deadline=QTimer(self);self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout);self.deadline.start(30000)

    def _loaded(self,ok):
        self.diagnostics.append(dict(level='load',message=str(ok)))
        if not ok:
            self._status('error','지도 화면을 불러오지 못했습니다.')

    def _timeout(self):
        if not self.tile_ready:
            self._status('error','위성 타일 연결 시간 초과 · 인터넷 연결을 확인하세요.')

    def _status(self,status,message):
        if status=='ready':
            self.web_ready=True
        elif status=='tiles':
            self.tile_ready=True;self.failed=False;self.deadline.stop()
        elif status in ('error','schematic'):
            self.failed=status=='error';self.user_schematic=status=='schematic'
            self.notice_label.setText(('위성지도 연결 실패 · ' if self.failed else '')+'개략 지도 표시')
            self.notice_label.setToolTip(message)
        self.diagnostics.append(dict(level=status,message=message))
        self.diagnostics=self.diagnostics[-30:]
        self.status_changed.emit(status)
        self.update()

    def retry_satellite(self):
        self.disabled=False;self.failed=False;self.user_schematic=False
        if self.web:
            self.web_ready=False;self.tile_ready=False
            self.web.reload();self.deadline.start(30000)
        self.update()

    def set_active(self,active):
        self.active=active
        if active:
            self.update()

    def update(self,*args):
        for name in ('track_id','trails','uncertainty','all_labels'):
            setattr(self.native,name,getattr(self,name))
        satellite=self.model.site=='airbase' and not self.disabled and not self.user_schematic and not self.failed
        if satellite and self.active:
            self._ensure_web()
        self.notice.setVisible(self.model.site=='airbase' and not satellite and not self.disabled)
        if satellite and self.web:
            if self.stack.currentWidget() is not self.web:
                self.stack.setCurrentWidget(self.web)
            if self.web_ready:
                payload=map_payload(self.model,self.track_id,dict(trails=self.trails,uncertainty=self.uncertainty,allLabels=self.all_labels))
                self.bridge.telemetry.emit(json.dumps(payload,ensure_ascii=False,separators=(',',':')))
            # Chromium owns this surface. Invalidating its parent at telemetry
            # frequency makes Qt repeatedly composite/erase the WebGL texture.
            return
        else:
            if self.stack.currentWidget() is not self.native:
                self.stack.setCurrentWidget(self.native)
            self.native.update()
        super().update(*args)
