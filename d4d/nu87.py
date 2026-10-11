"""USB indicator transport. Serial I/O never runs on the inference or GUI thread."""
from dataclasses import dataclass
import json
import logging
import os
from logging.handlers import RotatingFileHandler
import threading
import time

VID, PID = 0x10C4, 0xEA60
HELLO = 'NU87/1 READY DroneIndicator 1.0.0'
HEARTBEAT = 0.5
INPUT_LEASE = 1.0


def matching_port(ports):
    serial = os.environ.get('D4D_NU87_SERIAL', '').strip()
    if not serial:
        return None
    matches = [p.device for p in ports if p.vid == VID and p.pid == PID
               and p.serial_number == serial]
    return matches[0] if len(matches) == 1 else None


def should_alarm(mode, *, running, state='', fresh=False, demo_stale=True, tracks=()):
    """Consume the existing verdict, never promote a candidate/model score."""
    if not running:
        return False
    if mode == 'demo':
        return not demo_stale and bool(tracks)
    return mode in ('live', 'survey', 'replay') and fresh and state == 'DETECTED'


@dataclass(frozen=True)
class IndicatorStatus:
    state: str = 'SEARCHING'
    port: str = ''
    alarm: bool = False  # Last acknowledged board state, not just a queued request.
    detail: str = ''


class IndicatorClient:
    def __init__(self, *, port_provider=None, serial_factory=None, clock=time.monotonic,
                 log_path=None):
        self.clock = clock
        self.port_provider = port_provider
        self.serial_factory = serial_factory
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._wanted = False
        self._updated = -1e9
        self._status = IndicatorStatus()
        self._logger = logging.Logger('NU87', logging.INFO)
        if log_path:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(log_path, maxBytes=256_000, backupCount=2, encoding='utf-8')
                self._logger.addHandler(handler)
            except OSError:
                pass  # An unwritable optional log must not disable the indicator.
        self._logger.addHandler(logging.NullHandler())

    @property
    def status(self):
        with self._lock:
            return self._status

    def _publish(self, state, port='', alarm=False, detail=''):
        value = IndicatorStatus(state, port, alarm, detail)
        with self._lock:
            changed = value != self._status
            self._status = value
        if changed:
            self._logger.info(json.dumps(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                state=state, port=port, alarm=alarm, detail=detail), ensure_ascii=False))

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='NU87-Indicator', daemon=True)
            self._thread.start()

    def update(self, active):
        with self._lock:
            changed = self._wanted != bool(active)
            self._wanted, self._updated = bool(active), self.clock()
        if changed:
            self._wake.set()

    def desired(self):
        with self._lock:
            return self._wanted and self.clock() - self._updated < INPUT_LEASE

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        if not self._thread or not self._thread.is_alive():
            for handler in self._logger.handlers:
                handler.close()

    @staticmethod
    def exchange(link, command, expected):
        link.write((command + '\n').encode('ascii'))
        # AP association can briefly occupy AmebaD or emit SDK diagnostics.
        # Retain strict identity checking; allow a bounded ACK wait once identified.
        deadline = time.monotonic() + 1.0
        while True:
            answer = link.read_until(b'\n', 256).decode('ascii', errors='replace').strip()
            if answer == expected:
                return
            if command.endswith('HELLO') or answer.startswith('NU87/1 '):
                raise OSError(f'Unexpected indicator reply: {answer[:100]!r}')
            if time.monotonic() >= deadline:
                raise OSError('Indicator ACK timeout')

    def _run(self):
        try:
            if self.port_provider is None or self.serial_factory is None:
                import serial
                from serial.tools import list_ports
                self.port_provider = self.port_provider or list_ports.comports
                self.serial_factory = self.serial_factory or serial.Serial
        except ImportError:
            self._publish('ERROR', detail='pyserial 3.5 설치 필요')
            return
        while not self._stop.is_set():
            link = None
            port = ''
            verified = False
            try:
                port = matching_port(self.port_provider())
                if not port:
                    self._publish('DISCONNECTED')
                else:
                    self._publish('CONNECTING', port)
                    link = self.serial_factory(port=None, baudrate=115200, timeout=0.3, write_timeout=0.3)
                    link.dtr = False
                    link.rts = False
                    link.port = port
                    link.open()
                    # Boot messages and delayed UART startup are allowed only during handshake.
                    for attempt in range(6):
                        if self._stop.is_set():
                            break
                        link.reset_input_buffer()
                        try:
                            self.exchange(link, 'NU87/1 HELLO', HELLO)
                            verified = True
                            break
                        except OSError:
                            self._stop.wait(0.15)
                    if not verified:
                        raise OSError('DroneIndicator 펌웨어 응답 없음')
                    previous = None
                    sent_at = -1e9
                    while not self._stop.is_set():
                        active = self.desired()
                        if active != previous or self.clock() - sent_at >= HEARTBEAT:
                            self.exchange(link, f'NU87/1 SET {int(active)}',
                                          'NU87/1 OK ' + ('ALARM' if active else 'CLEAR'))
                            sent_at = self.clock()
                            previous = active
                            self._publish('CONNECTED', port, active)
                        self._wake.wait(0.05)
                        self._wake.clear()
            except (OSError, ValueError) as exc:
                self._publish('ERROR', port or '', detail=str(exc))
            finally:
                if link is not None:
                    try:
                        if verified and self._stop.is_set():
                            self.exchange(link, 'NU87/1 SET 0', 'NU87/1 OK CLEAR')
                    except (OSError, ValueError):
                        pass  # Firmware clears itself after 3 s without renewal.
                    try:
                        link.close()
                    except OSError:
                        pass
            self._stop.wait(2.0)
        self._publish('CLOSED')
