import time
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import HTTPException

from service.storage import Storage


class AuditRun:
    def __init__(self, storage: Storage, action: str, payload: Any):
        self.storage = storage
        self.action = action
        self.payload = payload
        self.started = time.perf_counter()
        self.closed = False

    def close(self, output: Any, status: str = "ok", error: str | None = None) -> None:
        if self.closed:
            return
        self.closed = True
        duration = max(0, int((time.perf_counter() - self.started) * 1000))
        self.storage.add_audit(self.action, self.payload, output, status, error, duration)


@contextmanager
def audited(storage: Storage, action: str, payload: Any) -> Iterator[AuditRun]:
    """Каждое действие фиксируется в audit_runs, включая отказы и необработанные ошибки."""
    run = AuditRun(storage, action, payload)
    try:
        yield run
    except HTTPException as exc:
        run.close({"detail": exc.detail}, "error", str(exc.detail))
        raise
    except Exception as exc:
        run.close({"detail": "internal error"}, "error", f"Внутренняя ошибка: {type(exc).__name__}")
        raise
    if not run.closed:
        run.close(None)
