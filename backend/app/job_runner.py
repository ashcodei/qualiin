"""Abstract job layer: submit(job_type, payload) -> job_id. Implementations: Celery or in-process thread pool."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .config import USE_CELERY

JOB_TYPE_PROCESS_PDF = "process_pdf"


class JobRunner(ABC):
    """Submit jobs by type and payload. Returns job_id (for revoke/pause) or None."""

    @abstractmethod
    def submit(self, job_type: str, payload: Dict[str, Any]) -> Optional[str]:
        """Enqueue a job. Returns job_id if the backend supports revoke (e.g. Celery task id), else None."""
        pass


class CeleryJobRunner(JobRunner):
    """Enqueue PDF processing to Celery. Returns Celery task_id so pause/revoke can use it."""

    def submit(self, job_type: str, payload: Dict[str, Any]) -> Optional[str]:
        if job_type != JOB_TYPE_PROCESS_PDF:
            return None
        from .celery_app import process_pdf_task
        from .db import set_doc_celery_task_id

        doc_id = payload.get("doc_id")
        filename = payload.get("filename", "")
        name = payload.get("name")
        description = payload.get("description")
        owner_id = payload.get("owner_id")
        result = process_pdf_task.delay(
            doc_id, filename, name=name, description=description, owner_id=owner_id
        )
        task_id = result.id if result else None
        if doc_id and task_id:
            set_doc_celery_task_id(doc_id, task_id)
        return task_id


class ThreadPoolJobRunner(JobRunner):
    """Run PDF processing in an in-process thread pool. Returns None (threads cannot be revoked by id)."""

    def submit(self, job_type: str, payload: Dict[str, Any]) -> Optional[str]:
        if job_type != JOB_TYPE_PROCESS_PDF:
            return None
        from .jobs import _enqueue_thread_pdf_job
        _enqueue_thread_pdf_job(payload)
        return None


_runner: Optional[JobRunner] = None


def get_runner() -> JobRunner:
    """Return the configured JobRunner (Celery or thread pool)."""
    global _runner
    if _runner is None:
        if USE_CELERY:
            _runner = CeleryJobRunner()
        else:
            _runner = ThreadPoolJobRunner()
    return _runner
