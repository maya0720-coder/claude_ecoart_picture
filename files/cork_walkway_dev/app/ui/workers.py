"""작업 스레드: 무거운 작업이 화면을 멈추지 않게 한다. 결과는 Qt 시그널로 메인 스레드에 전달.

QThreadPool 대신 Python 스레드 풀(ThreadPoolExecutor)을 쓰는 이유:
  QThreadPool 스레드에서 onnxruntime 세션을 만들고 다시 QThreadPool 스레드에서 실행하면
  힙 손상(0xc0000374)으로 프로그램이 죽는 것을 재현했다(Python 스레드에서는 문제없음).
  PySide가 작업마다 Python 스레드 상태를 만들고 지우는데, onnxruntime(pybind11)이 이를
  스레드별로 기억해 두었다가 지워진 상태를 다시 쓰는 것으로 추정된다.
수명 관리: 시그널 객체(QObject)가 자기 시그널 처리 중이나 작업 스레드에서 지워지지 않도록
  메인 스레드의 링 버퍼에 붙잡아 두었다가 충분히 지난 뒤(256개 뒤) 놓는다.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures

from PySide6.QtCore import QObject, Signal

log = logging.getLogger("corkwalkway")

# 사용자에게 그대로 보여줘도 되는(무엇이 안 됐는지 + 어떻게 하면 되는지) 예외
_FRIENDLY = (ValueError, FileNotFoundError, RuntimeError)


def user_message(e: BaseException) -> str:
    if isinstance(e, MemoryError):
        return "메모리가 부족합니다. 다른 프로그램을 닫거나 사진을 축소해 다시 시도하세요."
    if isinstance(e, _FRIENDLY) and str(e):
        return str(e)
    return f"처리 중 오류가 발생했습니다({type(e).__name__}). 다시 시도하고, 계속되면 사진을 다시 불러오세요."


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Worker:
    """fn(*args, **kw)를 작업 스레드에서 실행. 취소되면 결과를 버린다."""

    def __init__(self, label: str, fn, *args, **kw) -> None:
        self.label, self.fn, self.args, self.kw = label, fn, args, kw
        self.cancel = threading.Event()
        self.signals = _Signals()

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            result = self.fn(*self.args, **self.kw)
        except Exception as e:
            log.warning("작업 실패: 단계=%s 오류=%s 소요=%.2fs", self.label, type(e).__name__, time.perf_counter() - t0)
            if not self.cancel.is_set():
                self.signals.failed.emit(user_message(e))
            return
        log.info("작업 완료: 단계=%s 소요=%.2fs", self.label, time.perf_counter() - t0)
        if not self.cancel.is_set():
            self.signals.done.emit(result)


class Runner:
    """작업 시작·추적. 같은 이름(kind)의 새 작업이 오면 이전 결과는 버린다(오래된 결과가 덮어쓰지 않게)."""

    def __init__(self, max_workers: int | None = None) -> None:
        n = max_workers or max(2, min(6, (os.cpu_count() or 4) // 2))
        self.pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="cork")
        self._live: dict[str, Worker] = {}
        self._keep: deque = deque(maxlen=256)     # 시그널 객체를 메인 스레드에서 붙잡아 둠
        self._futures: set = set()

    def start(self, kind: str, fn, *args, on_done=None, on_fail=None, **kw) -> Worker:
        old = self._live.get(kind)
        if old is not None:
            old.cancel.set()
        w = Worker(kind, fn, *args, **kw)
        self._live[kind] = w
        self._keep.append(w.signals)

        def finish(handler, value):
            if self._live.get(kind) is w:
                del self._live[kind]
            if handler is not None and not w.cancel.is_set():
                handler(value)
        w.signals.done.connect(lambda r: finish(on_done, r))
        w.signals.failed.connect(lambda m: finish(on_fail, m))
        f = self.pool.submit(w.run)
        self._futures.add(f)
        f.add_done_callback(self._futures.discard)
        return w

    def cancel(self, kind: str) -> None:
        w = self._live.pop(kind, None)
        if w is not None:
            w.cancel.set()

    def busy(self, kind: str) -> bool:
        return kind in self._live

    def wait(self, msecs: int = 30000) -> bool:
        """모든 작업이 끝날 때까지 대기(시그널 전달은 이벤트 루프가 처리)."""
        _, pending = wait_futures(list(self._futures), timeout=msecs / 1000)
        return not pending

    def shutdown(self) -> None:
        for w in list(self._live.values()):
            w.cancel.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
