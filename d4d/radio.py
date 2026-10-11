"""Dedicated RX process, bounded shared latest-frame buffer, no disk I/O in callback.

RAW_IO uses the verified 2026.01.3 private first-pointer layout, matching the
existing Windows collection script. Other versions are rejected before access.
"""
import ctypes as C
import multiprocessing as mp
import os
import time
from .config import FS, FC, FRAME_BYTES, dll_directory


class Transfer(C.Structure):
    _fields_ = [("device", C.c_void_p), ("buffer", C.c_void_p),
                ("buffer_length", C.c_int), ("valid_length", C.c_int),
                ("rx_ctx", C.c_void_p), ("tx_ctx", C.c_void_p)]


class M0State(C.Structure):
    _fields_ = [("requested_mode", C.c_uint16), ("request_flag", C.c_uint16)] + [
        (name, C.c_uint32) for name in ("active_mode", "m0_count", "m4_count",
        "num_shortfalls", "longest_shortfall", "shortfall_limit", "threshold", "next_mode", "error")]


class BoardSerial(C.Structure):
    _fields_ = [("part_id", C.c_uint32 * 2), ("serial_no", C.c_uint32 * 4)]


CALLBACK = C.CFUNCTYPE(C.c_int, C.POINTER(Transfer))


def bind(lib, name, args, result=C.c_int):
    fn = getattr(lib, name)
    fn.argtypes, fn.restype = args, result
    return fn


def capture_process(settings, buffer, sequence, stamp, lock, stop, connection):
    device = C.c_void_p()
    started = initialized = False
    h = None
    try:
        # Capture is a small, isolated process; prioritize USB callback service.
        kernel = C.WinDLL("kernel32", use_last_error=True)
        bind(kernel, "GetCurrentProcess", [], C.c_void_p)
        bind(kernel, "SetPriorityClass", [C.c_void_p, C.c_uint32])
        priority_ok = bool(kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x80))
        folder = dll_directory()
        dll_search = os.add_dll_directory(str(folder))
        h = C.CDLL(str(folder / "hackrf-0.dll"))
        u = C.CDLL(str(folder / "libusb-1.0.dll"))
        bind(h, "hackrf_library_release", [], C.c_char_p)
        version = h.hackrf_library_release().decode()
        if version != "2026.01.3":
            raise RuntimeError(f"RAW_IO layout is not verified for libhackrf {version}.")
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
            "hackrf_stop_rx": [C.c_void_p], "hackrf_is_streaming": [C.c_void_p],
            "hackrf_get_m0_state": [C.c_void_p, C.POINTER(M0State)],
        }.items():
            bind(h, name, args)

        def check(name, *args):
            code = getattr(h, name)(*args)
            if code != 0:
                raise RuntimeError(f"{name}: {code}. HackRF 연결 및 다른 SDR 앱의 수신 상태를 확인하세요.")

        check("hackrf_init")
        initialized = True
        check("hackrf_open_by_serial", settings.serial.encode() or None, C.byref(device))
        board = BoardSerial()
        check("hackrf_board_partid_serialno_read", device, C.byref(board))
        serial = "".join(f"{word:08x}" for word in board.serial_no)
        usb = C.c_void_p.from_address(device.value).value
        supported = bind(u, "libusb_endpoint_supports_raw_io", [C.c_void_p, C.c_ubyte])(usb, 0x81)
        if supported != 1:
            raise RuntimeError(f"WinUSB RX RAW_IO unavailable ({supported})")
        rc = bind(u, "libusb_endpoint_set_raw_io", [C.c_void_p, C.c_ubyte, C.c_int])(usb, 0x81, 1)
        if rc != 0:
            raise RuntimeError(f"Enabling RAW_IO failed ({rc})")
        for name, val in (("hackrf_set_sample_rate", FS),
                          ("hackrf_set_baseband_filter_bandwidth", 20_000_000),
                          ("hackrf_set_freq", FC), ("hackrf_set_hw_sync_mode", 0),
                          ("hackrf_set_lna_gain", settings.lna), ("hackrf_set_vga_gain", settings.vga),
                          ("hackrf_set_amp_enable", 0), ("hackrf_set_antenna_enable", 0)):
            check(name, device, val)
        assembly = (C.c_ubyte * FRAME_BYTES)()
        address = C.addressof(assembly)
        target = C.addressof(buffer)
        offset = total = 0
        callback_error = []
        last_rx = time.perf_counter()

        @CALLBACK
        def receive(pointer):
            nonlocal offset, total, last_rx
            try:
                block = pointer.contents
                remaining, source_offset = block.valid_length, 0
                if remaining < 0 or remaining > block.buffer_length or remaining % 2:
                    raise ValueError("Invalid IQ transfer length")
                while remaining:
                    count = min(remaining, FRAME_BYTES - offset)
                    C.memmove(address + offset, block.buffer + source_offset, count)
                    offset += count
                    remaining -= count
                    source_offset += count
                    if offset == FRAME_BYTES:
                        with lock:
                            C.memmove(target, address, FRAME_BYTES)
                            sequence.value += 1
                            stamp.value = time.perf_counter()
                        offset = 0
                total += block.valid_length
                last_rx = time.perf_counter()
                return 0
            except BaseException as exc:
                callback_error.append(str(exc))
                return -1

        check("hackrf_start_rx", device, receive, None)
        started = True
        connection.send({"type": "ready", "raw_io": True, "library": version,
                         "high_priority": priority_ok, "serial": serial})
        last_stats, last_total = time.perf_counter(), 0
        while not stop.wait(0.1):
            now = time.perf_counter()
            if callback_error:
                raise RuntimeError(callback_error[0])
            if h.hackrf_is_streaming(device) != 1 or now - last_rx > 2:
                raise RuntimeError("HackRF 수신이 중단되었습니다. USB 연결을 확인하세요.")
            if now - last_stats >= 1:
                state = M0State()
                check("hackrf_get_m0_state", device, C.byref(state))
                connection.send({"type": "stats", "bytes": total,
                                 "mbps": (total - last_total) / (now - last_stats) / 1e6,
                                 "overruns": state.num_shortfalls, "device_error": state.error})
                last_stats, last_total = now, total
        before_stop = M0State()
        check("hackrf_get_m0_state", device, C.byref(before_stop))
        check("hackrf_stop_rx", device)
        started = False
        final_state = M0State()
        check("hackrf_get_m0_state", device, C.byref(final_state))
        connection.send({"type": "stopped", "bytes": total, "overruns": before_stop.num_shortfalls,
                         "after_stop_shortfalls": final_state.num_shortfalls,
                         "stop_shortfall_delta": max(0, final_state.num_shortfalls - before_stop.num_shortfalls),
                         "device_error": final_state.error, "frames": sequence.value})
    except BaseException as exc:
        try:
            connection.send({"type": "error", "message": str(exc)})
        except (BrokenPipeError, OSError):
            pass
    finally:
        if h:
            if started:
                h.hackrf_stop_rx(device)
            if device.value:
                h.hackrf_close(device)
            if initialized:
                h.hackrf_exit()
        connection.close()


class RadioStream:
    def __init__(self, settings):
        ctx = mp.get_context("spawn")
        self.buffer = ctx.RawArray(C.c_ubyte, FRAME_BYTES)
        self.sequence = ctx.RawValue(C.c_uint64, 0)
        self.stamp = ctx.RawValue(C.c_double, 0)
        self.lock, self.stop_event = ctx.Lock(), ctx.Event()
        self.connection, child = ctx.Pipe(duplex=False)
        self.child_connection = child
        self.process = ctx.Process(target=capture_process, args=(settings, self.buffer,
            self.sequence, self.stamp, self.lock, self.stop_event, child), daemon=True,
            name="D4D-HackRF-RX")

    def start(self):
        self.process.start()
        self.child_connection.close()

    def latest(self, after):
        # Bounded wait: a failed child must never deadlock the GUI worker.
        if not self.lock.acquire(timeout=0.1):
            return None
        try:
            if self.sequence.value <= after:
                return None
            return self.sequence.value, self.stamp.value, bytes(self.buffer)
        finally:
            self.lock.release()

    def messages(self):
        result = []
        try:
            while self.connection.poll():
                result.append(self.connection.recv())
        except (EOFError, OSError):
            pass
        return result

    def close(self):
        self.stop_event.set()
        if self.process.pid is None:
            self.connection.close()
            self.child_connection.close()
            return []
        self.process.join(4)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(2)
        final = self.messages()
        self.connection.close()
        return final
