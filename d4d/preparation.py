"""Bounded concurrent preprocessing, preserving exact reference pixels.

Only the newest completed frame is returned; inference never moves backward in
sample order. There are at most two full frames in flight and no growing queue.
"""
from concurrent.futures import ThreadPoolExecutor
import time
from .dsp import process_iq


def prepare(packet):
    seq, stamp, raw = packet
    start = time.perf_counter()
    gray, spectrum, signal = process_iq(raw)
    return seq, stamp, raw, gray, spectrum, signal, (time.perf_counter() - start) * 1000


class PreparedStream:
    def __init__(self, radio, workers=2):
        self.radio = radio
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="D4D-DSP")
        self.workers = workers
        self.pending = []
        self.last_scheduled = 0

    def latest(self, after):
        completed, active = [], []
        for future in self.pending:
            if future.done():
                result = future.result()
                if result[0] > after:
                    completed.append(result)
            else:
                active.append(future)
        self.pending = active
        if len(self.pending) < self.workers:
            packet = self.radio.latest(self.last_scheduled)
            if packet is not None:
                self.last_scheduled = packet[0]
                self.pending.append(self.pool.submit(prepare, packet))
        return max(completed, key=lambda r: r[0]) if completed else None

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
