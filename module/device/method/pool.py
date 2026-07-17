import abc
from collections import deque
from functools import partial
from itertools import count
from threading import Condition, Lock, Thread
from typing import TYPE_CHECKING, NoReturn, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType
    from typing import Self


def remove_tb_frames(exc: BaseException, n: int) -> BaseException:
    tb = exc.__traceback__
    for _ in range(n):
        if tb is None:
            return exc.with_traceback(None)
        tb = tb.tb_next
    return exc.with_traceback(tb)


class Outcome[ValueT](abc.ABC):
    @abc.abstractmethod
    def unwrap(self) -> ValueT:
        """返回封装值，或重新抛出封装的异常。"""


class Value[ValueT](Outcome[ValueT]):
    __slots__ = ("value",)

    def __init__(self, value: ValueT) -> None:
        self.value: ValueT = value

    def __repr__(self) -> str:
        return f"Value({self.value!r})"

    def unwrap(self) -> ValueT:
        return self.value


class Error(Outcome[NoReturn]):
    __slots__ = ("error",)

    def __init__(self, error: BaseException) -> None:
        self.error: BaseException = error

    def __repr__(self) -> str:
        return f"Error({self.error!r})"

    def unwrap(self) -> NoReturn:
        # Tracebacks show the 'raise' line below out of context, so let's give
        # this variable a name that makes sense out of context.
        captured_error = self.error
        try:
            raise captured_error
        finally:
            # We want to avoid creating a reference cycle here. Python does
            # collect cycles just fine, so it wouldn't be the end of the world
            # if we did create a cycle, but the cyclic garbage collector adds
            # latency to Python programs, and the more cycles you create, the
            # more often it runs, so it's nicer to avoid creating them in the
            # first place. For more details see:
            #
            #    https://github.com/python-trio/trio/issues/1770
            #
            # In particular, by deleting this local variables from the 'unwrap'
            # methods frame, we avoid the 'captured_error' object's
            # __traceback__ from indirectly referencing 'captured_error'.
            del captured_error, self


def capture[**P, ResultT](sync_fn: Callable[P, ResultT], *args: P.args, **kwargs: P.kwargs) -> Outcome[ResultT]:
    """将 sync_fn 的返回值或任意 BaseException 封装为 Outcome。"""
    try:
        return Value(sync_fn(*args, **kwargs))
    # 线程池 outcome 边界：需要把 KeyboardInterrupt 等跨线程异常传回调用方。
    except BaseException as exc:  # ruff:ignore[blind-except]
        exc = remove_tb_frames(exc, 1)
        return Error(exc)


class JobTimeout(Exception):
    pass


class _RunnableJob(Protocol):
    def run(self, worker: WorkerThread) -> None: ...


class _WaitableJob(Protocol):
    def wait(self) -> None: ...


class Job[ResultT]:
    """只允许一次 put 和一次 get 的单结果队列。"""

    def __init__(self, worker: WorkerThread, func: Callable[[], ResultT]) -> None:
        # Having attribute "worker" means job is ongoing
        # Not having attribute "worker" means job is finished
        self.worker: WorkerThread | None = worker
        self.func = func

        self.queue: deque[Outcome[ResultT]] = deque()
        self.notify_get = Lock()
        self.notify_get.acquire()

    def __repr__(self) -> str:
        return f"Job({self.func})"

    def wait(self) -> None:
        self.get()

    def get(self) -> ResultT:
        self.notify_get.acquire()

        item = self.queue.popleft()
        return item.unwrap()

    def get_or_timeout(self, timeout: float) -> ResultT:
        """timeout 秒内未完成则抛出 JobTimeout，底层调用继续占用原 worker。"""
        if self.notify_get.acquire(timeout=timeout):
            item = self.queue.popleft()
            return item.unwrap()
        raise JobTimeout

    def run(self, worker: WorkerThread) -> None:
        result = capture(self.func)

        # 先发布空闲状态，使结果回调可以立即复用当前线程。
        worker.thread_pool.mark_worker_idle(worker)

        self.queue.append(result)
        self.worker = None
        self.notify_get.release()


name_counter = count()


class WorkerThread:
    def __init__(self, thread_pool: WorkerPool) -> None:
        self.job: _RunnableJob | None = None
        self.thread_pool = thread_pool
        # This Lock is used in an unconventional way.
        #
        # "Unlocked" means we have a pending job that's been assigned to us;
        # "locked" means that we don't.
        #
        # Initially we have no job, so it starts out in locked state.
        self.worker_lock = Lock()
        self.worker_lock.acquire()
        self.default_name = f"Alasio thread {next(name_counter)}"

        self.thread = Thread(target=self._work, name=self.default_name, daemon=True)
        self.thread.start()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.default_name})"

    def _handle_job(self) -> None:
        # Convert to local variable, `self.job` will be another
        # value if new job is assigned
        job = self.job
        if job is None:
            raise RuntimeError
        del self.job
        job.run(self)

    def _work(self) -> None:
        while True:
            if self.worker_lock.acquire(timeout=WorkerPool.IDLE_TIMEOUT):
                self._handle_job()
            elif self.thread_pool.retire_idle_worker(self):
                return


class WorkerPool:
    """模仿 trio.to_thread.start_thread_soon() 的线程池。

    见 https://github.com/python-trio/trio/issues/6。
    """

    # 线程空闲 10 秒后退出。
    IDLE_TIMEOUT = 10

    def __init__(self, pool_size: int = 8) -> None:
        # 本地调用频率较低，默认使用小线程池。
        self.pool_size = pool_size

        self.idle_workers: dict[WorkerThread, None] = {}
        self.all_workers: dict[WorkerThread, None] = {}
        self._worker_available = Condition()

    def mark_worker_idle(self, worker: WorkerThread) -> None:
        with self._worker_available:
            self.idle_workers[worker] = None
            self._worker_available.notify()

    def retire_idle_worker(self, worker: WorkerThread) -> bool:
        with self._worker_available:
            if worker not in self.idle_workers:
                return False
            del self.idle_workers[worker]
            del self.all_workers[worker]
            self._worker_available.notify()
            return True

    def _get_thread_worker(self) -> WorkerThread:
        with self._worker_available:
            while True:
                try:
                    worker, _ = self.idle_workers.popitem()
                except KeyError:
                    pass
                else:
                    return worker

                if len(self.all_workers) < self.pool_size:
                    worker = WorkerThread(self)
                    self.all_workers[worker] = None
                    return worker

                self._worker_available.wait()

    def start_thread_soon[**P, ResultT](
        self, func: Callable[P, ResultT], *args: P.args, **kwargs: P.kwargs
    ) -> Job[ResultT]:
        """在线程中调用 func，返回可取得结果或异常的 Job。"""
        worker = self._get_thread_worker()
        job = Job(worker=worker, func=partial(func, *args, **kwargs))

        worker.job = job
        worker.worker_lock.release()
        return job

    def wait_jobs(self) -> WaitJobsWrapper:
        """上下文退出时等待其中所有 Job。"""
        return WaitJobsWrapper(self)


class WaitJobsWrapper:
    def __init__(self, pool: WorkerPool) -> None:
        self.pool: WorkerPool = pool
        self.jobs: list[_WaitableJob] = []

    def get(self) -> None:
        for job in self.jobs:
            job.wait()
        self.jobs.clear()

    def __enter__(self) -> Self:
        self.jobs.clear()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.get()

    def start_thread_soon[**P, ResultT](
        self, func: Callable[P, ResultT], *args: P.args, **kwargs: P.kwargs
    ) -> Job[ResultT]:
        job = self.pool.start_thread_soon(func, *args, **kwargs)
        self.jobs.append(job)
        return job


WORKER_POOL = WorkerPool()
