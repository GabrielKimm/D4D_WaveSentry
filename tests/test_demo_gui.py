import pytest
from PySide6.QtWidgets import QApplication, QSlider
from PySide6.QtCore import Qt
from d4d.gui import MainWindow


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,monkeypatch):
    monkeypatch.setenv('WAVESENTRY_DEMO_MAP','schematic')
    monkeypatch.setenv('D4D_NU87_DISABLED','1')
    def no_radio(*args,**kwargs):
        raise AssertionError('Demo must not construct a radio/inference engine')
    monkeypatch.setattr('d4d.gui.Engine',no_radio)
    monkeypatch.setattr('d4d.gui.SurveyEngine',no_radio)
    w=MainWindow(False)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.mode.setCurrentIndex(3)
    d=w.demo_panel;d.timer.stop();d.test_clock=[0.0]
    d.model.clock=lambda:d.test_clock[0];d.model.reset_scenario();d.refresh(False)
    d.timer.start()
    yield w
    w.close()


def test_demo_entry_shared_selection_and_pause(window):
    w=window;d=w.demo_panel
    assert w.engine is None and w.thread is None
    assert w.view_stack.currentWidget() is d and d.timer.isActive()
    assert w.source_label.text()=='TRACKING'
    assert not d.findChildren(QSlider)
    assert d.rows['H-01'].isHidden() and d.selected=='F-01'
    d.test_clock[0]=3.2;d.refresh()
    w.start_button.click()
    assert not d.model.running
    assert d.values['speed'].text()=='—'
    assert d.rows['H-01'].text(3)=='—'
    w.start_button.click()
    assert d.model.running and d.values['speed'].text()!='—'
    d.table.setCurrentItem(d.rows['F-02'])
    assert d.selected==d.map.track_id==d.evidence.track_id=='F-02'
    assert d.values['course'].text()==d.rows['F-02'].text(3)
    d.search.setText('적군')
    assert d.rows['F-01'].isHidden() and not d.rows['H-01'].isHidden()


def test_bearing_does_not_expose_position_or_motion(window):
    d=window.demo_panel
    d.test_clock[0]=3.2;d.refresh()
    d.model.set_mode('bearing');d.select('H-01')
    for key in ['distance','speed','course']:
        assert d.values[key].text()=='—'
    assert d.rows['H-01'].text(1)==d.rows['H-01'].text(2)==d.rows['H-01'].text(3)=='—'
    assert d.rows['F-01'].text(2)!='—'
    d.model.set_mode('lost');d.refresh(False)
    assert d.values['distance'].text()=='—'


def test_modes_and_event_log_are_isolated(window):
    w=window;d=w.demo_panel
    real_events=w.log_table.topLevelItemCount()
    for i in range(30):
        d.add_event('TEST',str(i))
    assert d.events.topLevelItemCount()==18
    assert w.log_table.topLevelItemCount()==real_events
    for index in [0,1,2]:
        w.mode.setCurrentIndex(index)
        assert not d.timer.isActive() and not d.model.running
        assert w.source_label.text()=='RX ONLY'
        assert w.records_stack.currentIndex()==0
        assert w.view_stack.currentIndex()==(1 if index==2 else 0)
    w.mode.setCurrentIndex(3)
    assert d.timer.isActive() and d.model.running
    assert not w.snapshot_button.isEnabled()


def test_render_scenes_and_small_window(window,app):
    w=window;w.show()
    d=w.demo_panel
    for width,height in [(1500,960),(1130,790)]:
        w.resize(width,height);w.reset_layout()
        for site in ['airbase','facility','stage']:
            w.demo_site.setCurrentIndex(w.demo_site.findData(site))
            d.model.reset_scenario();d.test_clock[0]+=8.5;d.refresh()
            app.processEvents()
            assert not w.grab().isNull()
            assert d.model.site==site
            assert len(d.map.label_boxes)==5
            for item in d.rows.values():
                rect=d.table.visualItemRect(item)
                assert rect.top()>=0 and rect.bottom()<=d.table.viewport().height()
            for i,(ident,rect) in enumerate(d.map.label_boxes):
                assert d.map.rect().contains(rect.toRect())
                for _,other in d.map.label_boxes[i+1:]:
                    assert not rect.intersects(other), (width,site,ident)


def test_contact_removal_selection_counts_and_entry_reset(window):
    d=window.demo_panel
    d.test_clock[0]=3;d.refresh()
    assert d.selected==d.map.track_id==d.evidence.track_id=='H-01'
    d.test_clock[0]=8;d.refresh()
    assert d.selected=='H-02' and '적군 2' in d.counts.text()
    for _ in range(40):
        d.test_clock[0]=d.model.next_event;d.refresh()
        ids={t['id'] for t in d.model.tracks()}
        assert d.selected==d.map.track_id==d.evidence.track_id and d.selected in ids
        assert {ident for ident,row in d.rows.items() if not row.isHidden()}==ids
        assert len(d.rows)==5
    assert d.events.topLevelItemCount()==18
    window.mode.setCurrentIndex(0);window.mode.setCurrentIndex(3)
    assert d.model.scenario_time==0 and d.rows['H-01'].isHidden() and d.rows['H-02'].isHidden()
    assert d.selected=='F-01' and '적군 0' in d.counts.text()
