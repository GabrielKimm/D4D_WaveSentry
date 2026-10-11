"""Synthetic local-coordinate tracks. No radio, geolocation or ML inference."""
from dataclasses import dataclass
from collections import deque
from math import atan2, cos, degrees, hypot, pi, sin, sqrt
import random
import time


@dataclass(frozen=True)
class Scene:
    title: str
    name: str
    array: str
    radius: float
    zone: float
    error: float


SCENES = {
    'airbase': Scene('대구 11전비 / 위성지도', 'DAEGU', 'RX-A', 2000, 570, 45),
    'facility': Scene('특수시설 / BRAVO', 'FACILITY / BRAVO', 'RX-B', 800, 220, 18),
    'stage': Scene('소규모 무대 / CHARLIE', 'VENUE / CHARLIE', 'RX-C', 300, 80, 8),
}
SPECS = (
    ('F-01', '아군', '#a4dcc8', -.44, -.10, .19, .30, 4.3, 220, 1, 2.44, .91, '허용 목록 일치 가정'),
    ('F-02', '아군', '#a4dcc8', .22, -.43, .28, .13, .45, 190, -1, 2.46, .89, '허용 목록 일치 가정'),
    ('H-01', '적군', '#efa58e', .44, .28, .32, .24, 2.7, 180, 1, 5.80, .94, '시나리오 지정'),
    ('U-01', '미식별', '#d5c287', -.34, .52, .19, .11, 1.1, 260, -1, 5.76, .76, '식별 근거 부족'),
    ('H-02', '적군', '#efa58e', -.54, .05, .24, .29, .6, 210, -1, 5.82, .92, '시나리오 지정'),
)
TRACK_IDS = tuple(s[0] for s in SPECS)
HOSTILE_IDS = ('H-01', 'H-02')
SPOT_DURATION = 2.4


def angle(x, y):
    return degrees(atan2(x, y)) % 360


def degree(value):
    return f'{round(value) % 360:03d}°'


def course_text(value):
    return '↑↗→↘↓↙←↖'[int((value + 22.5) // 45) % 8] + ' ' + degree(value)


def sample_tracks(t, site='airbase', ident=None):
    scene = SCENES[site]
    result = []
    for track_id, affiliation, color, cx, cy, rx, ry, phase, period, sign, freq, score, basis in SPECS:
        if ident is not None and ident != track_id:
            continue
        omega = 2 * pi / (period * sqrt(scene.radius / 2000)) * sign
        a = phase + t * omega
        x, y = scene.radius * (cx + rx * cos(a)), scene.radius * (cy + ry * sin(a))
        vx, vy = -scene.radius * rx * sin(a) * omega, scene.radius * ry * cos(a) * omega
        distance = hypot(x, y)
        result.append(dict(id=track_id, affiliation=affiliation, color=color, x=x, y=y, vx=vx, vy=vy,
                           speed=hypot(vx, vy), course=angle(vx, vy), distance=distance,
                           bearing=angle(x, y), radial=(x * vx + y * vy) / distance,
                           freq=freq, score=score + .012 * sin(t * .8 + phase), basis=basis))
    return result


def threat(track, site):
    zone = SCENES[site].zone
    if track['distance'] <= zone:
        return 'inside', '보호구역 진입'
    if track['distance'] < zone * 1.85 and track['radial'] < 0:
        return 'approach', '보호구역 접근'
    return ('inbound', '적군 기체 접근') if track['radial'] < 0 else ('outbound', '적군 기체 이탈')


class DemoModel:
    """Monotonic, unbounded simulation; missing observations never invent motion."""
    def __init__(self, clock=time.monotonic, rng=None):
        self.clock = clock
        self.rng = rng or random.Random()
        self.site = 'airbase'
        self.mode = 'position'
        self.last_observation_mode = 'position'
        self.running = False
        self.elapsed = 0.0
        self.last = clock()
        self.frozen_at = 0.0
        self.held_since = None
        self.reset_scenario()

    def reset_scenario(self, ready=True):
        """Restart the presentation on entry; a loading map does not consume cues."""
        self.elapsed = self.frozen_at = self.scenario_time = 0.0
        self.last = self.clock()
        self.scenario_ready = ready
        self.next_event = 3.0
        self.opening = 0
        self.hostiles = {}
        self.events = deque(maxlen=64)

    def set_scene_ready(self):
        if not self.scenario_ready:
            self.advance()
            self.scenario_ready = True

    def _advance_scenario(self, dt):
        self.scenario_time += dt
        # Only two reusable identities; no growing entity list or per-track timers.
        while self.scenario_time >= self.next_event:
            at = self.next_event
            ident = HOSTILE_IDS[self.opening] if self.opening < 2 else self.rng.choice(HOSTILE_IDS)
            if ident in self.hostiles:
                del self.hostiles[ident]
                kind = 'lost'
            else:
                self.hostiles[ident] = at
                kind = 'spot'
            self.events.append(dict(kind=kind, id=ident, time=at))
            self.opening = min(2, self.opening + 1)
            self.next_event = 8.0 if self.opening == 1 else at + self.rng.uniform(3, 5)

    def take_events(self):
        events = list(self.events)
        self.events.clear()
        return events

    def spot_pulses(self):
        if self.stale:
            return []
        return [dict(id=ident, age=self.scenario_time-born,
                     bearing=sample_tracks(0, self.site, ident)[0]['bearing'])
                for ident, born in self.hostiles.items()
                if 0 <= self.scenario_time-born < SPOT_DURATION]

    @property
    def stale(self):
        return not self.running or self.mode == 'lost'

    @property
    def observed_time(self):
        return self.frozen_at if self.stale else self.elapsed

    @property
    def age(self):
        return max(0, self.clock() - self.held_since) if self.held_since is not None else 0

    def advance(self):
        now = self.clock()
        dt = max(0, now - self.last)
        if self.running:
            self.elapsed += dt
        if not self.stale and self.scenario_ready:
            self._advance_scenario(dt)
        self.last = now

    def set_running(self, running):
        self.advance()
        was_stale = self.stale
        if not was_stale:
            self.frozen_at = self.elapsed
        self.running = running
        self._update_hold(was_stale)

    def set_mode(self, mode):
        if mode not in ('position', 'bearing', 'lost'):
            raise ValueError(mode)
        self.advance()
        was_stale = self.stale
        if not was_stale:
            self.frozen_at = self.elapsed
        self.mode = mode
        if not self.stale:
            self.last_observation_mode = mode
        self._update_hold(was_stale)

    def _update_hold(self, was_stale):
        if self.stale and not was_stale:
            self.held_since = self.clock()
        elif not self.stale:
            self.held_since = None
            self.last_observation_mode = self.mode

    def tracks(self):
        return [sample_tracks(self.scenario_time-self.hostiles[ident]
                              if ident in self.hostiles else self.observed_time,
                              self.site, ident)[0]
                for ident in TRACK_IDS if ident not in HOSTILE_IDS or ident in self.hostiles]

    def trail(self, ident):
        """A new contact has no history before its current acquisition."""
        if ident in HOSTILE_IDS:
            if ident not in self.hostiles:
                return []
            t = self.scenario_time-self.hostiles[ident]
            start = max(0, t-60)
        else:
            t = self.observed_time
            start = t-60
        times = [start+i*2 for i in range(int((t-start)/2))] + [t]
        return [sample_tracks(at, self.site, ident)[0] for at in times]

    def bearing_only(self, track):
        return self.last_observation_mode == 'bearing' and track['id'] == 'H-01'
