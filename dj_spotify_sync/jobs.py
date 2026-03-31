from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock, Thread
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


@dataclass
class JobState:
    job_id: str
    job_type: str
    status: str = "queued"
    progress_current: int = 0
    progress_total: Optional[int] = None
    progress_percent: Optional[float] = None
    current_message: str = "Queued"
    warnings_count: int = 0
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, JobState] = {}
        self._lock = Lock()

    def create_job(self, job_type: str) -> JobState:
        job = JobState(job_id=str(uuid4()), job_type=job_type)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def start_job(self, job: JobState, target: Callable[[], Dict[str, Any]]) -> None:
        thread = Thread(target=self._run_job, args=(job.job_id, target), daemon=True)
        thread.start()

    def _run_job(self, job_id: str, target: Callable[[], Dict[str, Any]]) -> None:
        self.set_running(job_id, message="Starting...")
        try:
            result = target()
            self.complete(job_id, result=result)
        except Exception as exc:
            self.fail(job_id, str(exc))

    def set_running(self, job_id: str, message: Optional[str] = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            if job.started_at is None:
                job.started_at = datetime.now(timezone.utc).isoformat()
            if message:
                job.current_message = message

    def update_progress(
        self,
        job_id: str,
        current: int,
        total: Optional[int],
        message: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.progress_current = max(current, 0)
            job.progress_total = total if total is None or total >= 0 else None
            if job.progress_total and job.progress_total > 0:
                pct = (job.progress_current / job.progress_total) * 100
                job.progress_percent = max(0.0, min(100.0, round(pct, 2)))
            else:
                job.progress_percent = None
            job.current_message = message
            if extra and "warnings_count" in extra:
                job.warnings_count = int(extra["warnings_count"])

    def complete(self, job_id: str, result: Dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "completed"
            job.result = result
            job.finished_at = datetime.now(timezone.utc).isoformat()
            if job.progress_total is not None:
                job.progress_current = job.progress_total
                job.progress_percent = 100.0

    def fail(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "failed"
            job.error_message = message
            job.current_message = "Failed"
            job.finished_at = datetime.now(timezone.utc).isoformat()

    def get_job(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def to_dict(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "status": job.status,
                "progress_current": job.progress_current,
                "progress_total": job.progress_total,
                "progress_percent": job.progress_percent,
                "current_message": job.current_message,
                "warnings_count": job.warnings_count,
                "error_message": job.error_message,
                "result": job.result,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "created_at": job.created_at,
            }


job_manager = JobManager()
