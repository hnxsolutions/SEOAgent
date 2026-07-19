"""Tests for the durable queue client fallback + monitor gating."""
from app.queue import client as qclient
from app.services.queue_monitor import QueueMonitor


class _Bg:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args):
        self.tasks.append((func, args))


def test_enqueue_or_background_falls_back_when_queue_unavailable(monkeypatch):
    # Queue unavailable -> enqueue_job returns None -> BackgroundTasks used.
    monkeypatch.setattr(qclient, "enqueue_job", lambda *a, **k: None)
    bg = _Bg()

    def real_job(x, y):
        return None

    mode = qclient.enqueue_or_background(bg, "app.queue.jobs.run_seo_run", real_job, "id1", "ten1")
    assert mode == "background"
    assert len(bg.tasks) == 1
    assert bg.tasks[0][1] == ("id1", "ten1")


def test_enqueue_or_background_uses_queue_when_available(monkeypatch):
    class _Job:
        id = "job-123"

    monkeypatch.setattr(qclient, "enqueue_job", lambda *a, **k: _Job())
    bg = _Bg()
    mode = qclient.enqueue_or_background(bg, "app.queue.jobs.run_seo_run", lambda *a: None, "id1", "ten1")
    assert mode == "queued"
    assert bg.tasks == []  # not run in-process


def test_get_queue_none_when_disabled(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "QUEUE_ENABLED", False)
    assert qclient.get_queue() is None


def test_queue_monitor_disabled_status(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "QUEUE_ENABLED", False)
    stats = QueueMonitor().stats()
    assert stats["status"] == "disabled"
    assert stats["dead_letter"] == 0
    assert QueueMonitor().failed_jobs() == []
    assert QueueMonitor().requeue_failed("x") is False
