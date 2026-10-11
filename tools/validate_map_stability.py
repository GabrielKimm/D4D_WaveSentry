"""Measure the actual Qt WebEngine composite during continuous track updates."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['D4D_NU87_DISABLED'] = '1'
import numpy as np
from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from d4d.gui import MainWindow

parser = argparse.ArgumentParser()
parser.add_argument('--name', default='after')
parser.add_argument('--width', type=int, default=1500)
parser.add_argument('--height', type=int, default=960)
args = parser.parse_args()
out = Path(__file__).resolve().parents[1] / 'output/map_stability'
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
w = MainWindow(False)
w.setWindowTitle('WaveSentry · 지도 안정성 검수')
w.resize(args.width, args.height)
w.reset_layout()
w.mode.setCurrentIndex(3)
w.demo_panel.model.rng.seed(17)
w.show()

class PaintCount(QObject):
    count = 0
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Paint:
            self.count += 1
        return False

counter = PaintCount()
w.demo_panel.map.installEventFilter(counter)
started = time.monotonic()
sampling = None
baseline = None
samples = []
errors = []
cue_captures = set()
exit_code = 1

INSTRUMENT = '''(() => {
 const stats=window.__stability={sceneFrames:0, labelReplacements:0, contextLost:0,
   renderCalls:0,renderMs:0,maxRenderMs:0,maxLabelOverlaps:0,maxFurnitureOverlaps:0,maxCachedLabels:0};
 const renderFrame=render;
 render=()=>{const start=performance.now();renderFrame();const ms=performance.now()-start;
   stats.renderCalls++;stats.renderMs+=ms;stats.maxRenderMs=Math.max(stats.maxRenderMs,ms);
   stats.maxLabelOverlaps=Math.max(stats.maxLabelOverlaps,metrics.labelOverlaps);
   stats.maxFurnitureOverlaps=Math.max(stats.maxFurnitureOverlaps,metrics.furnitureOverlaps);
   stats.maxCachedLabels=Math.max(stats.maxCachedLabels,document.getElementById('labels').childElementCount);
 };
 viewer.scene.postRender.addEventListener(()=>stats.sceneFrames++);
 viewer.canvas.addEventListener('webglcontextlost',()=>stats.contextLost++);
 new MutationObserver(records=>{for(const r of records){
   if(r.type==='childList' && r.target.classList?.contains('track-label')) stats.labelReplacements++;
 }}).observe(document.getElementById('labels'),{childList:true,subtree:true});
 return true;
})()'''

def finish(raw='{}'):
    global exit_code
    timer.stop()
    try:
        renderer = json.loads(raw or '{}')
    except ValueError:
        renderer = {}
    report = dict(name=args.name, size=[w.width(),w.height()],
        seconds=round(time.monotonic()-(sampling or started),2),
        sampleCount=len(samples), nativeMapPaints=counter.count,
        samples=samples, renderer=renderer, errors=errors, native=w.demo_panel.map.diagnostics,
        engineStarted=w.engine is not None)
    report['backgroundFlashFrames'] = sum(s['medianBackgroundDelta'] > 20 for s in samples)
    report['hudFlashFrames'] = sum(s['hudDelta'] > 20 for s in samples)
    report['maxBackgroundDelta'] = max((s['medianBackgroundDelta'] for s in samples), default=0)
    states=renderer.get('metrics',{})
    report['success'] = (len(samples)>=80 and not errors and not report['backgroundFlashFrames']
                         and not report['hudFlashFrames'] and not renderer.get('metrics',{}).get('contextLost')
                         and not renderer.get('diagnostics',{}).get('errors')
                         and not states.get('maxLabelOverlaps') and not states.get('maxFurnitureOverlaps')
                         and states.get('maxCachedLabels',0)<=5)
    exit_code = 0 if report['success'] else 1
    (out/f'{args.name}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    w.grab().save(str(out/f'{args.name}.png'))
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},ensure_ascii=True),flush=True)
    w.close()

def poll():
    global sampling, baseline
    m = w.demo_panel.map
    if m.failed or time.monotonic()-started>65:
        errors.append('Map failed to load or timed out')
        finish()
        return
    if not m.tile_ready:
        return
    if sampling is None:
        sampling = time.monotonic()
        m.web.page().runJavaScript(INSTRUMENT)
        counter.count = 0
        return
    if time.monotonic()-sampling<2:
        return
    model=w.demo_panel.model
    for cue,at in [('waiting',2),('first_spot',4.0),('second_spot',9.0),('settled',10.6)]:
        if model.scenario_time>=at and cue not in cue_captures:
            cue_captures.add(cue)
            w.grab().save(str(out/f'{args.name}_{cue}.png'))
    pix = m.web.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    width,height = pix.width(),pix.height()
    arr = np.frombuffer(pix.constBits(),np.uint8).reshape(height,pix.bytesPerLine())[:,:width*4].reshape(height,width,4)[:,:,:3]
    # Edge terrain regions remain outside the new animated surveillance ring.
    # The old central probes intersected the intended red glow in compact views.
    patches=[]
    for x,y in [(.02,.52),(.02,.69),(.95,.66),(.04,.13)]:
        left,top=int(width*x),int(height*y)
        patches.append(arr[top:top+24,left:left+24].astype(np.int16))
    if baseline is None:
        baseline=patches
    deltas=[float(np.abs(p-b).mean()) for p,b in zip(patches,baseline)]
    samples.append(dict(time=round(time.monotonic()-sampling,3),scenarioTime=round(model.scenario_time,3),
        activeIds=[d['id'] for d in model.tracks()],pulses=model.spot_pulses(),
        medianBackgroundDelta=round(float(np.median(deltas[:3])),3),hudDelta=round(deltas[3],3)))
    if len(samples) in (1,40,80):
        pix.save(str(out/f'{args.name}_frame_{len(samples):03d}.png'))
    if len(samples)>=80:
        timer.stop()
        m.web.page().runJavaScript('JSON.stringify({metrics:window.__stability,diagnostics:window.satelliteDiagnostics(),creditsVisible:!!document.querySelector(".provider"),body:document.body.innerText})',finish)

timer=QTimer()
timer.timeout.connect(poll)
timer.start(200)
app.exec()
sys.exit(exit_code)
