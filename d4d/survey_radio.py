"""One isolated device owner: firmware sweep, stop/drain, fixed-frequency IQ dwell.

Sweep wire format and INTERLEAVED tuning follow libhackrf's documented API
and hackrf_sweep v2026.01.3. Sweep samples are NEVER fed to the image model.
"""
import ctypes as C
import multiprocessing as mp
import os
import queue
import time
import numpy as np
from .radio import bind, CALLBACK, M0State, BoardSerial
from .config import FS, FRAME_BYTES, dll_directory

BLOCK = 16384
FFT = 1024
TAIL_SAMPLES = 4096
SWEEP_SAMPLE_SECONDS = TAIL_SAMPLES / FS


def merge_sweeps(parts, ranges, wall_seconds):
    low, high = ranges[0][0], ranges[-1][1]
    power = np.full(high-low, np.nan, dtype=np.float32)
    stamps = np.zeros(high-low, dtype=np.float64)
    clips = np.zeros(high-low, dtype=np.float32)
    for part in parts:
        sl = slice(part['low']-low, part['high']-low)
        power[sl], stamps[sl], clips[sl] = part['power'], part['stamps'], part['clips']
    bins = sum(b-a for a,b in ranges)
    quality = {k: sum(p['quality'][k] for p in parts) for k in parts[0]['quality']}
    return dict(type='sweep', low=low, high=high, ranges=ranges, power=power, stamps=stamps, clips=clips,
                coverage_pct=float(np.isfinite(power).sum()/bins*100), first=parts[0]['first'],
                ended=parts[-1]['ended'], wall_seconds=wall_seconds, quality=quality,
                segment_quality=[p['quality'] for p in parts], strategy='sequential_disjoint_ranges',
                sample_seconds_per_bin=SWEEP_SAMPLE_SECONDS)


def sweep_tiles(raw):
    """Yield (left edge MHz, 512 frequency bins, PSD dBFS/bin, clip%).

    Four Hann periodograms from the tail of each settled firmware block.
    Two inner 5 MHz slices exclude DC and the analog filter's outer edges.
    """
    if len(raw) % BLOCK:
        raise ValueError("Partial firmware sweep block")
    window = np.hanning(FFT).astype(np.float32)
    offsets = np.fft.fftfreq(FFT, 1 / FS) / 1e6
    indices = np.r_[np.arange(640, 896), np.arange(128, 384)]
    for pos in range(0, len(raw), BLOCK):
        block = raw[pos:pos + BLOCK]
        if block[:2] != b"\x7f\x7f":
            raise ValueError("Invalid firmware sweep header")
        edge = int.from_bytes(block[2:10], "little") / 1e6
        components = np.frombuffer(block[-TAIL_SAMPLES * 2:], np.int8).astype(np.float32)
        iq = components.view(np.complex64).reshape(-1, FFT) / 128
        power = np.mean(np.abs(np.fft.fft(iq * window, axis=1)) ** 2, axis=0) / FFT ** 2
        db = 10 * np.log10(np.maximum(power[indices], 1e-16))
        yield edge, edge + 7.5 + offsets[indices], db, float(np.mean(np.abs(components) >= 127) * 100)


class Device:
    def __init__(self, settings):
        self.device = C.c_void_p()
        self.started = self.initialized = False
        self.folder_handle = os.add_dll_directory(str(dll_directory()))
        self.h = C.CDLL(str(dll_directory() / "hackrf-0.dll"))
        self.u = C.CDLL(str(dll_directory() / "libusb-1.0.dll"))
        self.callback = None
        self.info = {}
        try:
            self._open(settings)
        except BaseException:
            self.close()
            raise

    def _open(self, settings):
        h = self.h
        bind(h, "hackrf_library_release", [], C.c_char_p)
        version = h.hackrf_library_release().decode()
        if version != "2026.01.3":
            raise RuntimeError(f"Unverified RAW_IO layout: {version}")
        for name, args in {
            "hackrf_init": [], "hackrf_exit": [],
            "hackrf_open_by_serial": [C.c_char_p, C.POINTER(C.c_void_p)],
            "hackrf_close": [C.c_void_p],
            "hackrf_board_partid_serialno_read": [C.c_void_p, C.POINTER(BoardSerial)],
            "hackrf_set_sample_rate": [C.c_void_p, C.c_double],
            "hackrf_set_baseband_filter_bandwidth": [C.c_void_p, C.c_uint32],
            "hackrf_set_freq": [C.c_void_p, C.c_uint64],
            "hackrf_set_lna_gain": [C.c_void_p, C.c_uint32],
            "hackrf_set_vga_gain": [C.c_void_p, C.c_uint32],
            "hackrf_set_amp_enable": [C.c_void_p, C.c_uint8],
            "hackrf_set_antenna_enable": [C.c_void_p, C.c_uint8],
            "hackrf_set_hw_sync_mode": [C.c_void_p, C.c_uint8],
            "hackrf_start_rx": [C.c_void_p, CALLBACK, C.c_void_p],
            "hackrf_start_rx_sweep": [C.c_void_p, CALLBACK, C.c_void_p],
            "hackrf_init_sweep": [C.c_void_p, C.POINTER(C.c_uint16), C.c_int, C.c_uint32,
                                  C.c_uint32, C.c_uint32, C.c_int],
            "hackrf_stop_rx": [C.c_void_p], "hackrf_is_streaming": [C.c_void_p],
            "hackrf_get_m0_state": [C.c_void_p, C.POINTER(M0State)],
        }.items():
            bind(h, name, args)
        self.check("hackrf_init")
        self.initialized = True
        self.check("hackrf_open_by_serial", settings.serial.encode() or None, C.byref(self.device))
        board = BoardSerial()
        self.check("hackrf_board_partid_serialno_read", self.device, C.byref(board))
        usb = C.c_void_p.from_address(self.device.value).value
        supported = bind(self.u, "libusb_endpoint_supports_raw_io", [C.c_void_p, C.c_ubyte])(usb, 0x81)
        if supported != 1:
            raise RuntimeError(f"RX RAW_IO unavailable: {supported}")
        code = bind(self.u, "libusb_endpoint_set_raw_io", [C.c_void_p, C.c_ubyte, C.c_int])(usb, 0x81, 1)
        if code:
            raise RuntimeError(f"RAW_IO failed: {code}")
        kernel = C.WinDLL("kernel32", use_last_error=True)
        bind(kernel, "GetCurrentProcess", [], C.c_void_p)
        bind(kernel, "SetPriorityClass", [C.c_void_p, C.c_uint32])
        priority = bool(kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x80))
        for name, value in (("hackrf_set_sample_rate", FS), ("hackrf_set_hw_sync_mode", 0),
                            ("hackrf_set_lna_gain", settings.lna), ("hackrf_set_vga_gain", settings.vga),
                            ("hackrf_set_amp_enable", 0), ("hackrf_set_antenna_enable", 0)):
            self.check(name, self.device, value)
        self.info = dict(serial="".join(f"{n:08x}" for n in board.serial_no), library=version,
                         raw_io=True, high_priority=priority)

    def check(self, name, *args):
        code = getattr(self.h, name)(*args)
        if code:
            raise RuntimeError(f"{name}: {code}; HackRF 연결 / 다른 수신 앱을 확인하세요.")

    def state(self):
        state = M0State()
        self.check("hackrf_get_m0_state", self.device, C.byref(state))
        return state

    def start(self, sweep=False):
        self.q = queue.Queue(maxsize=64)
        self.drops = 0
        self.callback_error = None
        self.accepting = True
        @CALLBACK
        def receive(pointer):
            try:
                block = pointer.contents
                if not 0 < block.valid_length <= block.buffer_length or block.valid_length % 2:
                    raise ValueError("Invalid transfer length")
                if self.accepting:
                    data = C.string_at(block.buffer, block.valid_length)
                    try:
                        self.q.put_nowait((time.perf_counter(), data))
                    except queue.Full:
                        self.drops += 1
                return 0
            except BaseException as exc:
                self.callback_error = str(exc)
                return -1
        self.callback = receive
        self.check("hackrf_start_rx_sweep" if sweep else "hackrf_start_rx", self.device, receive, None)
        self.started = True

    def packet(self, deadline, stop):
        while not stop.is_set() and time.perf_counter() < deadline:
            if self.callback_error:
                raise RuntimeError(self.callback_error)
            try:
                return self.q.get(timeout=0.05)
            except queue.Empty:
                if self.h.hackrf_is_streaming(self.device) != 1:
                    raise RuntimeError("HackRF stream stopped")
        if stop.is_set():
            raise InterruptedError("Capture cancelled")
        raise TimeoutError("No complete HackRF capture within deadline")

    def finish(self):
        # Deliberate stop shortfalls are kept separately from running shortfalls.
        self.accepting = False
        before = self.state()
        self.check("hackrf_stop_rx", self.device)
        self.started = False
        after = self.state()
        return dict(overruns=int(before.num_shortfalls), device_error=int(before.error),
                    stop_shortfalls=max(0, int(after.num_shortfalls) - int(before.num_shortfalls)),
                    host_dropped_transfers=self.drops)

    def sweep(self, low, high, stop, ranges=None):
        # Firmware needs whole 20 MHz interleaved steps; crop result to the user's range.
        ranges = tuple(tuple(r) for r in (ranges or [(low, high)]))
        if not ranges or len(ranges) > 10 or any(not 1 <= a < b <= 6000 for a, b in ranges):
            raise ValueError("Invalid sweep ranges")
        if any(b > c for (_, b), (c, _) in zip(ranges, ranges[1:])):
            raise ValueError("Sweep ranges must be sorted and disjoint")
        if len(ranges) > 1:
            # On the attached n_251213/r9 firmware native two-range sweeps yielded
            # exactly 3 running shortfalls per pass. Separate passes measured 0.
            # Do not mask the counter; avoid that path and retain per-range quality.
            began = time.perf_counter()
            parts = [self.sweep(a, b, stop) for a, b in ranges]
            return merge_sweeps(parts, ranges, time.perf_counter()-began)
        low, high = ranges[0][0], ranges[-1][1]
        edges = [v for a, b in ranges for v in (a, min(6000, a + ((b - a + 19) // 20) * 20))]
        frequencies = (C.c_uint16 * len(edges))(*edges)
        self.check("hackrf_set_baseband_filter_bandwidth", self.device, 15_000_000)
        self.check("hackrf_init_sweep", self.device, frequencies, len(ranges), BLOCK, FS, 7_500_000, 1)
        sums = np.zeros(high - low, dtype=np.float64)
        counts = np.zeros(high - low, dtype=np.int32)
        stamps = np.zeros(high - low, dtype=np.float64)
        clips = np.zeros(high - low, dtype=np.float32)
        requested = np.zeros(high - low, dtype=bool)
        for a, b in ranges:
            requested[a - low:b - low] = True
        started = time.perf_counter()
        first = None
        self.start(sweep=True)
        done = False
        while not done:
            stamp, raw = self.packet(started + 15, stop)
            for edge, freq, db, clip in sweep_tiles(raw):
                if edge == low:
                    if first is not None:
                        done = True
                        break
                    first = stamp
                if first is None:
                    continue
                indices = np.floor(freq).astype(int) - low
                valid = (indices >= 0) & (indices < len(sums))
                valid &= requested[np.clip(indices, 0, len(sums) - 1)]
                idx = indices[valid]
                np.add.at(sums, idx, 10 ** (db[valid] / 10))
                np.add.at(counts, idx, 1)
                stamps[np.unique(idx)] = stamp
                clips[np.unique(idx)] = clip
        quality = self.finish()
        seen = counts > 0
        values = np.full(high - low, np.nan, dtype=np.float32)
        values[seen] = 10 * np.log10(sums[seen] / counts[seen])
        return dict(type="sweep", low=low, high=high, ranges=ranges, power=values, stamps=stamps, clips=clips,
                    coverage_pct=float(seen[requested].mean() * 100), first=first, ended=time.perf_counter(),
                    wall_seconds=time.perf_counter() - started, quality=quality,
                    sample_seconds_per_bin=SWEEP_SAMPLE_SECONDS)

    def dwell(self, center_hz, frames, stop):
        if not 1_000_000 <= center_hz <= 6_000_000_000 or not 1 <= frames <= 8:
            raise ValueError("Invalid dwell request")
        self.check("hackrf_set_baseband_filter_bandwidth", self.device, 20_000_000)
        self.check("hackrf_set_freq", self.device, center_hz)
        started = time.perf_counter()
        self.start()
        pending = bytearray()
        discarded = 0
        result = []
        while len(result) < frames:
            stamp, raw = self.packet(started + 5, stop)
            pending.extend(raw)
            while len(pending) >= FRAME_BYTES and len(result) < frames:
                data = bytes(pending[:FRAME_BYTES])
                del pending[:FRAME_BYTES]
                if discarded < 4:  # 80 ms settling after stream restart; never stitch tunes.
                    discarded += 1
                else:
                    result.append((stamp, data))
        quality = self.finish()
        return dict(type="dwell", center_hz=center_hz, frames=result, quality=quality,
                    discarded_settling_seconds=discarded * 0.02,
                    wall_seconds=time.perf_counter() - started)

    def close(self):
        if self.started:
            self.h.hackrf_stop_rx(self.device)
            self.started = False
        if self.device.value:
            self.h.hackrf_close(self.device)
            self.device = C.c_void_p()
        if self.initialized:
            self.h.hackrf_exit()
            self.initialized = False
        self.folder_handle.close()


def radio_worker(settings, pipe, stop):
    device = None
    try:
        device = Device(settings)
        pipe.send(dict(type="ready", **device.info))
        while not stop.is_set():
            if not pipe.poll(0.05):
                continue
            command = pipe.recv()
            if command["type"] == "sweep":
                pipe.send(device.sweep(command["low"], command["high"], stop, command.get("ranges")))
            elif command["type"] == "dwell":
                pipe.send(device.dwell(command["center_hz"], command["frames"], stop))
            else:
                raise ValueError("Unknown radio command")
    except InterruptedError:
        pass
    except BaseException as exc:
        try:
            pipe.send(dict(type="error", message=str(exc)))
        except (OSError, EOFError):
            pass
    finally:
        if device:
            device.close()
        pipe.close()


class SurveyRadio:
    def __init__(self, settings, stop_event):
        ctx = mp.get_context("spawn")
        self.pipe, child = ctx.Pipe()
        self.stop_flag = ctx.Event()
        self.parent_stop = stop_event
        self.process = ctx.Process(target=radio_worker, args=(settings, child, self.stop_flag), daemon=True)
        self.process.start()
        child.close()

    def receive(self, timeout=20):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if self.parent_stop.is_set():
                self.stop_flag.set()
                raise InterruptedError("Survey cancelled")
            if self.pipe.poll(0.05):
                message = self.pipe.recv()
                if message["type"] == "error":
                    raise RuntimeError(message["message"])
                return message
            if not self.process.is_alive():
                raise RuntimeError("Survey radio process exited")
        raise TimeoutError("Survey radio response timed out")

    def request(self, kind, **kwargs):
        self.pipe.send(dict(type=kind, **kwargs))
        return self.receive()

    def close(self):
        self.stop_flag.set()
        # Drain responses so a child sending a bounded IQ packet can finish.
        deadline = time.perf_counter() + 4
        while self.process.is_alive() and time.perf_counter() < deadline:
            if self.pipe.poll(0.05):
                try:
                    self.pipe.recv()
                except (EOFError, OSError):
                    break
        self.process.join(0.2)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(2)
        self.pipe.close()
