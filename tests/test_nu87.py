import threading
import time
from types import SimpleNamespace
import pytest
from d4d.nu87 import (IndicatorClient, IndicatorStatus, VID, PID,
                      HELLO, matching_port, should_alarm)


@pytest.fixture(autouse=True)
def configured_board(monkeypatch):
    monkeypatch.setenv('D4D_NU87_SERIAL', 'TEST-NU87')


def port(serial='TEST-NU87', device='COM9'):
    return SimpleNamespace(vid=VID, pid=PID, serial_number=serial, device=device)


def test_unconfigured_board_does_not_open_an_arbitrary_usb_uart(monkeypatch):
    monkeypatch.delenv('D4D_NU87_SERIAL')
    assert matching_port([port()]) is None


def wait_for(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    assert predicate()


@pytest.mark.parametrize('mode', ['live', 'survey', 'replay'])
def test_only_fresh_confirmed_detection_can_alarm(mode):
    for state in ['CANDIDATE', 'STALE', 'QUALITY', 'GAP', 'CLEAR', 'STOPPED', 'ERROR']:
        assert not should_alarm(mode, running=True, fresh=True, state=state)
    assert should_alarm(mode, running=True, fresh=True, state='DETECTED')
    assert not should_alarm(mode, running=False, fresh=True, state='DETECTED')
    assert not should_alarm(mode, running=True, fresh=False, state='DETECTED')


def test_demo_alarm_requires_current_observation():
    assert should_alarm('demo', running=True, demo_stale=False, tracks=[{}])
    assert not should_alarm('demo', running=True, demo_stale=True, tracks=[{}])
    assert not should_alarm('demo', running=False, demo_stale=False, tracks=[{}])
    assert not should_alarm('demo', running=True, demo_stale=False, tracks=[])


def test_port_identity_is_not_just_com_number_or_cp210_chip():
    assert matching_port([port('OTHER', 'COM8'), port()]) == 'COM9'
    assert matching_port([port('OTHER')]) is None
    assert matching_port([port(), port(device='COM10')]) is None
    assert matching_port([port(device='COM12')]) == 'COM12'


class FakeSerial:
    def __init__(self, **kwargs):
        self.commands = []
        self.is_open = False
        self.fail = False
        self.identity = HELLO
        self.answer = b''

    def open(self):
        assert self.dtr is False and self.rts is False
        self.is_open = True

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        pass

    def write(self, value):
        if self.fail:
            raise OSError('USB disconnected')
        command = value.decode().strip()
        self.commands.append(command)
        reply = self.identity if command.endswith('HELLO') else 'NU87/1 OK ' + ('ALARM' if command.endswith('1') else 'CLEAR')
        self.answer = (reply + '\n').encode()

    def read_until(self, *args):
        return self.answer


def test_worker_acknowledges_heartbeat_expires_input_and_clears_on_close():
    link = FakeSerial()
    client = IndicatorClient(port_provider=lambda: [port()], serial_factory=lambda **kw: link)
    client.start()
    try:
        wait_for(lambda: client.status.state == 'CONNECTED')
        client.update(True)
        wait_for(lambda: client.status.alarm)
        wait_for(lambda: link.commands.count('NU87/1 SET 1') >= 2)
        # GUI stopped refreshing: old DETECTED must not be renewed forever.
        wait_for(lambda: not client.status.alarm)
        client.update(True)
        wait_for(lambda: client.status.alarm)
    finally:
        client.close()
    assert link.commands[-1] == 'NU87/1 SET 0'
    assert not link.is_open and not client._thread.is_alive()


def test_unplug_then_reconnect_recovers_without_affecting_app():
    links = []
    def factory(**kw):
        link = FakeSerial(); links.append(link); return link
    client = IndicatorClient(port_provider=lambda: [port()], serial_factory=factory)
    client.start()
    try:
        wait_for(lambda: client.status.state == 'CONNECTED')
        links[0].fail = True
        wait_for(lambda: client.status.state == 'ERROR')
        assert not client.status.alarm
        wait_for(lambda: len(links) >= 2 and client.status.state == 'CONNECTED', 4)
        client.update(True)
        wait_for(lambda: client.status.alarm)
    finally:
        client.close()


def test_unknown_firmware_never_receives_alarm_command():
    link = FakeSerial(); link.identity = 'OTHER DEVICE'
    client = IndicatorClient(port_provider=lambda: [port()], serial_factory=lambda **kw: link)
    client.update(True); client.start()
    try:
        wait_for(lambda: client.status.state == 'ERROR')
    finally:
        client.close()
    assert link.commands and all(c == 'NU87/1 HELLO' for c in link.commands)


def test_wifi_join_delay_and_sdk_noise_do_not_break_identified_ack():
    replies = iter([b'', b'[wifi] station associated\r\n', b'\r\n', b'NU87/1 OK ALARM\r\n'])
    commands = []
    link = SimpleNamespace(write=commands.append, read_until=lambda *args: next(replies))
    IndicatorClient.exchange(link, 'NU87/1 SET 1', 'NU87/1 OK ALARM')
    assert commands == [b'NU87/1 SET 1\n']  # Wait, never duplicate the command.


def test_wrong_protocol_ack_still_fails_immediately():
    link = SimpleNamespace(write=lambda data: None, read_until=lambda *args: b'NU87/1 ERROR COMMAND\n')
    with pytest.raises(OSError, match='Unexpected indicator reply'):
        IndicatorClient.exchange(link, 'NU87/1 SET 1', 'NU87/1 OK ALARM')


def test_ack_wait_has_a_deadline(monkeypatch):
    clock = iter([0, .4, 1.1])
    monkeypatch.setattr(time, 'monotonic', lambda: next(clock))
    link = SimpleNamespace(write=lambda data: None, read_until=lambda *args: b'')
    with pytest.raises(OSError, match='ACK timeout'):
        IndicatorClient.exchange(link, 'NU87/1 SET 0', 'NU87/1 OK CLEAR')


def test_gui_modes_pause_stale_and_stop_share_indicator_policy(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from d4d.gui import MainWindow
    from d4d import nu87_gui
    class Client:
        status = IndicatorStatus('CONNECTED', 'COM9')
        def __init__(self, **kw): self.active = False
        def start(self): pass
        def update(self, active): self.active = active
        def close(self): self.active = False
    monkeypatch.setattr(nu87_gui, 'IndicatorClient', Client)
    monkeypatch.delenv('D4D_NU87_DISABLED', raising=False)
    app = QApplication.instance() or QApplication([])
    w = MainWindow(False)
    try:
        controller = w.nu87_indicator
        w.mode.setCurrentIndex(3)
        controller.refresh(); assert controller.client.active
        w.demo_panel.toggle()
        controller.refresh(); assert not controller.client.active
        w.demo_panel.toggle(); w.demo_panel.model.set_mode('lost')
        controller.refresh(); assert not controller.client.active
        w.mode.setCurrentIndex(0)
        w.thread = SimpleNamespace(is_alive=lambda: True)
        w.engine = SimpleNamespace(stop_event=threading.Event())
        w.current_state = 'DETECTED'; w.last_seen = time.monotonic()
        controller.refresh(); assert controller.client.active
        w.last_seen -= 2
        controller.refresh(); assert not controller.client.active
        w.last_seen = time.monotonic(); w.engine.stop_event.set()
        controller.refresh(); assert not controller.client.active
        w.thread = None
        w.mode.setCurrentIndex(2)
        w.thread = SimpleNamespace(is_alive=lambda: True)
        w.engine.stop_event.clear()
        model = w.survey_dashboard.model
        model.set_lifecycle('READY')
        t = time.perf_counter()
        model.ingest(dict(generated_mono=t,phase='REVISIT',processed=12,visits=1,
            survey_ranges=((2400,2500),(5150,5890)),
            evidence_regions=[dict(id='RF-1',last_seen=t,score=2,episodes=4,supported=True,low_mhz=5790,high_mhz=5810)],
            sweep=dict(quality_flags=[],seconds=.1),
            zoom=dict(center_mhz=5800,record=dict(last_mono=t),ended=t,observed_mono=t,quality_flags=[],boxes=[])))
        controller.refresh(); assert controller.client.active
        model.set_lifecycle('STOPPING')
        controller.refresh(); assert not controller.client.active
    finally:
        w.thread = None
        w.close()
    assert not controller.client.active
