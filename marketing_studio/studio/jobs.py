"""백그라운드 작업 실행기 — 단일 워커 스레드 큐 (브라우저/ffmpeg 작업 직렬화)."""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from typing import Any, Callable

from studio.db import Store
from studio.models import Job

log = logging.getLogger("studio.jobs")

ProgressFn = Callable[[str, int | None], None]
JobFn = Callable[[Job, ProgressFn], dict[str, Any] | None]


class JobCancelled(RuntimeError):
    pass


class JobRunner:
    def __init__(self, store: Store, workers: int = 1) -> None:
        self.store = store
        self._queue: queue.Queue[tuple[str, JobFn]] = queue.Queue()
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        for i in range(max(1, workers)):
            t = threading.Thread(target=self._worker, name=f"studio-job-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    # ------------------------------------------------------------------ public
    def submit(self, job_type: str, payload: dict[str, Any], fn: JobFn) -> Job:
        job = Job(type=job_type, payload=payload, status="queued", message="대기 중")
        self.store.save_job(job)
        self._queue.put((job.id, fn))
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        if not job or job.status not in ("queued", "running"):
            return False
        with self._lock:
            self._cancelled.add(job_id)
        if job.status == "queued":
            job.status = "cancelled"
            job.message = "취소됨"
            self.store.save_job(job)
        return True

    def get(self, job_id: str) -> Job | None:
        return self.store.get_job(job_id)

    def wait(self, job_id: str, timeout: float = 120, poll: float = 0.2) -> Job | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.store.get_job(job_id)
            if job and job.status in ("done", "failed", "cancelled"):
                return job
            time.sleep(poll)
        return self.store.get_job(job_id)

    def pending(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------ worker
    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def _worker(self) -> None:
        while True:
            job_id, fn = self._queue.get()
            job = self.store.get_job(job_id)
            if job is None:
                continue
            if self._is_cancelled(job_id):
                job.status = "cancelled"
                job.message = "취소됨"
                self.store.save_job(job)
                continue
            job.status = "running"
            job.message = "시작"
            job.progress = max(job.progress, 1)
            self.store.save_job(job)

            def progress(message: str, pct: int | None = None, _job: Job = job) -> None:
                if self._is_cancelled(_job.id):
                    raise JobCancelled("사용자 취소")
                _job.message = str(message)[:300]
                if pct is not None:
                    _job.progress = int(max(_job.progress, min(99, pct)))
                self.store.save_job(_job)

            try:
                result = fn(job, progress) or {}
                job.result = result
                job.status = "done"
                job.progress = 100
                job.message = job.message if job.message and job.message != "시작" else "완료"
            except JobCancelled:
                job.status = "cancelled"
                job.message = "취소됨"
            except Exception as e:  # noqa: BLE001
                job.status = "failed"
                job.error = f"{type(e).__name__}: {str(e)[:600]}"
                job.message = "실패"
                log.error("작업 실패 %s (%s): %s\n%s", job.id, job.type, e, traceback.format_exc())
            finally:
                with self._lock:
                    self._cancelled.discard(job_id)
                self.store.save_job(job)
