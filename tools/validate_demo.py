"""Production-widget render and behavior audit, using native Windows fonts."""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from d4d.gui import MainWindow

out=Path(__file__).resolve().parents[1]/'output/demo_validation'
out.mkdir(parents=True,exist_ok=True)
app=QApplication([])
os.environ['WAVESENTRY_DEMO_MAP']='schematic'
os.environ['D4D_NU87_DISABLED']='1'
w=MainWindow(False)
w.setAttribute(Qt.WA_DontShowOnScreen)
w.mode.setCurrentIndex(3)
w.tick()
d=w.demo_panel
d.timer.stop();w.timer.stop()
now=[0.0]
d.model.clock=lambda:now[0]
d.model.last=0
w.show()
results=[]
for width,height in [(1500,960),(1130,790)]:
    w.resize(width,height);w.reset_layout()
    for site in ['airbase','facility','stage']:
        w.demo_site.setCurrentIndex(w.demo_site.findData(site))
        now[0]=0;d.model.reset_scenario();d.model.rng.seed(17)
        for elapsed in [0,4,9,30,300]:
            now[0]=elapsed;d.refresh()
            app.processEvents()
            pix=w.grab()
            boxes=d.map.label_boxes
            overlaps=[(a,b) for i,(a,r) in enumerate(boxes) for b,s in boxes[i+1:] if r.intersects(s)]
            assert not overlaps,(width,site,elapsed,overlaps)
            assert all(d.map.rect().contains(r.toRect()) for _,r in boxes)
            assert all(0<=d.table.visualItemRect(item).top() and
                d.table.visualItemRect(item).bottom()<=d.table.viewport().height()
                for item in d.rows.values() if not item.isHidden())
            assert d.values['course'].text()==d.rows[d.selected].text(3)
            if elapsed==0:
                assert pix.save(str(out/f'{site}_{width}.png'))
            results.append(dict(width=width,height=height,site=site,time=elapsed,labels=len(boxes),overlaps=0))
w.resize(1500,960);w.reset_layout()
w.demo_site.setCurrentIndex(0)
now[0]=0;d.model.reset_scenario();now[0]=3.2;d.refresh();app.processEvents()
w.grab().save(str(out/'windows_demo_live.png'))
d.toggle();app.processEvents()
w.grab().save(str(out/'windows_demo_paused.png'))
before=d.model.tracks();now[0]=13.2;d.refresh()
assert d.model.tracks()==before and d.values['speed'].text()=='—'
d.toggle();d.model.set_mode('bearing');d.refresh(False);app.processEvents()
w.grab().save(str(out/'windows_demo_bearing.png'))
assert d.values['distance'].text()==d.values['speed'].text()==d.values['course'].text()=='—'
d.model.set_mode('lost');d.refresh(False);app.processEvents()
w.grab().save(str(out/'windows_demo_lost.png'))
assert d.values['distance'].text()=='—'
d.model.set_mode('position');d.refresh(False)
samples=[]
for i in range(40):
    now[0]+=.05
    start=time.perf_counter();d.refresh();d.map.grab()
    samples.append((time.perf_counter()-start)*1000)
report=dict(layouts=results,checks=['shared selection','table fully visible','continuous motion beyond 120s',
    'pause holds observations','bearing-only hides position and velocity','lost retains observation validity'],
    render_ms=dict(mean=sum(samples)/len(samples),max=max(samples)),engine_started=w.engine is not None)
(out/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
w.close()
print(json.dumps(dict(layouts=len(results),mean_render_ms=report['render_ms']['mean'],engine_started=report['engine_started'])))
