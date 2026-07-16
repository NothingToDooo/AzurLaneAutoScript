from threading import Event

import pytest

from module.device.method.pool import JobTimeout, WorkerPool


def test_timeout_keeps_worker_owned_until_the_call_really_finishes() -> None:
    release = Event()
    pool = WorkerPool(pool_size=1)
    job = pool.start_thread_soon(lambda: release.wait(timeout=1))
    worker = job.worker
    assert worker is not None

    with pytest.raises(JobTimeout):
        job.get_or_timeout(0.01)

    assert worker.thread.is_alive()
    assert worker in pool.all_workers

    release.set()
    assert job.get()
    assert worker in pool.idle_workers
