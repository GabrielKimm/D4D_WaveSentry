from concurrent.futures import Future
from d4d.preparation import PreparedStream


class FakeRadio:
    def latest(self, after):
        return None


def completed(sequence):
    future = Future()
    future.set_result((sequence, 0, b"", None, None, None, 0))
    return future


def test_completed_frames_never_go_backwards():
    stream = PreparedStream(FakeRadio())
    try:
        stream.pending = [completed(12), completed(10)]
        assert stream.latest(9)[0] == 12
        stream.pending = [completed(11)]
        assert stream.latest(12) is None
        assert not stream.pending
    finally:
        stream.close()


def test_pending_work_remains_bounded():
    stream = PreparedStream(FakeRadio(), workers=2)
    a, b = Future(), Future()
    stream.pending = [a, b]
    try:
        assert stream.latest(0) is None
        assert len(stream.pending) == 2
    finally:
        a.cancel()
        b.cancel()
        stream.close()


def test_engine_imports_and_stop_is_nonblocking():
    from d4d.engine import Engine
    from d4d.config import Settings
    e = Engine(Settings())
    e.stop()
    assert e.stop_event.is_set()
