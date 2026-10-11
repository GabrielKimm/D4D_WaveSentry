"""Run the actual embedded WebGL view and save renderer diagnostics + native capture."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from d4d.gui import MainWindow

os.environ['D4D_NU87_DISABLED'] = '1'

parser=argparse.ArgumentParser()
parser.add_argument('--keep-open',action='store_true')
parser.add_argument('--width',type=int,default=1500)
parser.add_argument('--height',type=int,default=960)
parser.add_argument('--fixed-size',action='store_true')
args=parser.parse_args()
out=Path(__file__).resolve().parents[1]/'output/satellite_validation'
out.mkdir(parents=True,exist_ok=True)
app=QApplication([])
w=MainWindow(False);w.setWindowTitle('WaveSentry · SATELLITE 검수')
w.resize(args.width,args.height);w.reset_layout();w.mode.setCurrentIndex(3)
if args.fixed_size:w.setFixedSize(args.width,args.height)
def demo_only():
    w.mode.setEnabled(False)
    for button,action in zip(w.page_buttons[:3],w.mode_actions[:3]):
        button.setEnabled(False);action.setEnabled(False)
w.timer.timeout.connect(demo_only);demo_only();w.show()
started=time.monotonic();last={};finished=False;passed=False
def inspected(raw):
    global last
    if raw:
        try:last=json.loads(raw)
        except (TypeError,ValueError):pass
def finish(success):
    global finished,passed
    if finished:return
    finished=True;passed=success;timer.stop()
    m=w.demo_panel.map
    report=dict(success=success,elapsed=time.monotonic()-started,renderer=last,
        native=m.diagnostics,webReady=m.web_ready,tileReady=m.tile_ready,failed=m.failed,
        engineStarted=w.engine is not None,size=[w.width(),w.height()])
    (out/f'validation_{args.width}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    w.grab().save(str(out/f'windows_satellite_{args.width}.png'))
    print(json.dumps(report,ensure_ascii=True),flush=True)
    if not args.keep_open:w.close()
def poll():
    m=w.demo_panel.map
    if m.web:
        m.web.page().runJavaScript('JSON.stringify({...(window.satelliteDiagnostics ? window.satelliteDiagnostics() : {}),documentState:document.readyState,cesium:typeof Cesium,channel:typeof QWebChannel,transport:typeof qt,body:document.body?.innerText?.slice(-400)})',inspected)
    elapsed=time.monotonic()-started
    if elapsed>8 and last.get('tiles') and last.get('frames',0)>30:
        finish(last.get('labelOverlaps')==0 and last.get('furnitureOverlaps')==0 and last.get('chromeOverlaps')==0 and not last.get('errors'))
    elif elapsed>40 or m.failed:
        finish(False)
timer=QTimer();timer.timeout.connect(poll);timer.start(1000)
app.exec()
sys.exit(0 if passed else 1)
