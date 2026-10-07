"""
인메모리 job 상태 관리

job_id → {status, source_path, result_path, segments, created_at}
status: "uploaded" | "analyzing" | "analyzed" | "rendering" | "done" | "error"
"""
import threading
from datetime import datetime, timezone
from typing import Any


_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create_job(job_id: str, source_path: str, filename: str) -> dict:
    job = {
        "job_id": job_id,
        "filename": filename,
        "status": "uploaded",
        "source_path": source_path,
        "result_path": None,
        "result_url": None,
        "segments": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _jobs[job_id] = job
    return job


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def update_job(job_id: str, **kwargs) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        job.update(kwargs)
        return dict(job)


def require_job(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}'를 찾을 수 없습니다.")
    return job
