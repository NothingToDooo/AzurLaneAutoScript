from threading import Condition, Event, Lock, Thread

import pytest

from module.device.method.pool import Job, JobTimeoutError, WorkerPool


class _ObservedCondition(Condition):
    def __init__(self, expected_waiters: int) -> None:
        super().__init__()
        self.waiters_ready = Event()
        self._expected_waiters = expected_waiters
        self._active_waiters = 0
        self._waiter_count_lock = Lock()

    def wait(self, timeout: float | None = None) -> bool:
        with self._waiter_count_lock:
            self._active_waiters += 1
            if self._active_waiters == self._expected_waiters:
                self.waiters_ready.set()
        try:
            return super().wait(timeout)
        finally:
            with self._waiter_count_lock:
                self._active_waiters -= 1


def test_full_pool_accepts_multiple_concurrent_submitters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_first = Event()
    pool = WorkerPool(pool_size=1)
    worker_available = _ObservedCondition(expected_waiters=2)
    monkeypatch.setattr(pool, "_worker_available", worker_available)
    first_job = pool.start_thread_soon(release_first.wait)
    result_lock = Lock()
    jobs: list[Job[int]] = []
    errors: list[RuntimeError] = []

    def submit(value: int) -> None:
        try:
            job = pool.start_thread_soon(lambda: value)
        except RuntimeError as exc:
            with result_lock:
                errors.append(exc)
        else:
            with result_lock:
                jobs.append(job)

    submitters = [Thread(target=submit, args=(value,), daemon=True) for value in (1, 2)]
    for submitter in submitters:
        submitter.start()

    waiters_registered = False
    try:
        waiters_registered = worker_available.waiters_ready.wait(timeout=1)
    finally:
        release_first.set()

    assert first_job.get_or_timeout(1)

    for submitter in submitters:
        submitter.join(timeout=1)

    assert waiters_registered
    assert not errors
    assert all(not submitter.is_alive() for submitter in submitters)
    assert sorted(job.get_or_timeout(1) for job in jobs) == [1, 2]
    assert len(pool.all_workers) == 1


def test_idle_worker_exits_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WorkerPool, "IDLE_TIMEOUT", 0.01)
    release = Event()
    pool = WorkerPool(pool_size=1)
    job = pool.start_thread_soon(lambda: release.wait(timeout=1))
    worker = job.worker
    assert worker is not None

    release.set()
    assert job.get_or_timeout(1)
    worker.thread.join(timeout=1)

    assert not worker.thread.is_alive()
    assert worker not in pool.idle_workers
    assert worker not in pool.all_workers


def test_timeout_keeps_worker_owned_until_the_call_really_finishes() -> None:
    release = Event()
    pool = WorkerPool(pool_size=1)
    job = pool.start_thread_soon(lambda: release.wait(timeout=1))
    worker = job.worker
    assert worker is not None

    with pytest.raises(JobTimeoutError):
        job.get_or_timeout(0.01)

    assert worker.thread.is_alive()
    assert worker in pool.all_workers

    release.set()
    assert job.get_or_timeout(1)
    assert worker in pool.idle_workers
