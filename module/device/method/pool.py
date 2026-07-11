import abc
import ctypes
from collections import deque
from functools import wraps
from itertools import count
from threading import Lock, Thread
from typing import NoReturn, TypeVar

from module.logger import logger

ResultT = TypeVar("ResultT")


def remove_tb_frames(exc, n: int):
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

    def __init__(self, value: ValueT):
        self.value: ValueT = value

    def __repr__(self) -> str:
        return f"Value({self.value!r})"

    def unwrap(self) -> ValueT:
        return self.value


class Error(Outcome[NoReturn]):
    __slots__ = ("error",)

    def __init__(self, error: BaseException):
        self.error: BaseException = error

    def __repr__(self) -> str:
        return f"Error({self.error!r})"

    def unwrap(self):
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


def capture(sync_fn, *args, **kwargs):
    """将 sync_fn 的返回值或任意 BaseException 封装为 Outcome。"""
    try:
        return Value(sync_fn(*args, **kwargs))
    # 线程池 outcome 边界：需要把 _JobKill、KeyboardInterrupt 等跨线程异常传回调用方。
    except BaseException as exc:  # noqa: BLE001
        exc = remove_tb_frames(exc, 1)
        return Error(exc)


class JobError(Exception):
    pass


class JobTimeout(Exception):
    pass


class _JobKill(Exception):
    pass


class Job[ResultT]:
    """只允许一次 put 和一次 get 的单结果队列。"""

    def __init__(self, worker, func_args_kwargs):
        # Having attribute "worker" means job is ongoing
        # Not having attribute "worker" means job is finished or killed
        self.worker = worker
        self.func_args_kwargs = func_args_kwargs

        self.queue: deque[Outcome[ResultT]] = deque()
        self.put_lock = Lock()
        self.notify_get = Lock()
        self.notify_get.acquire()

    def __repr__(self):
        return f"Job({self.func_args_kwargs})"

    def get(self) -> ResultT:
        self.notify_get.acquire()

        item = self.queue.popleft()
        return item.unwrap()

    def get_or_kill(self, timeout) -> ResultT:
        """timeout 秒内未完成则终止线程并抛出 JobTimeout。

        线程池已满时，JobTimeout 可能无法立即抛出。
        """
        if self.notify_get.acquire(timeout=timeout):
            item = self.queue.popleft()
            return item.unwrap()
        self._kill()
        raise JobTimeout

    def _kill(self):
        with self.put_lock:
            try:
                worker = self.worker
            except AttributeError:
                return
            worker.kill()
            del self.worker


name_counter = count()


class WorkerThread:
    def __init__(self, thread_pool):
        self.job: Job | None = None
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

    def __repr__(self):
        return f"{self.__class__.__name__}({self.default_name})"

    def _handle_job(self) -> None:
        # Convert to local variable, `self.job` will be another
        # value if new job is assigned
        job = self.job
        if job is None:
            raise RuntimeError
        del self.job
        func, args, kwargs = job.func_args_kwargs

        result = capture(func, *args, **kwargs)

        # Tell the cache that we're available to be assigned a new
        # job. We do this *before* calling 'deliver', so that if
        # 'deliver' triggers a new job, it can be assigned to us
        # instead of spawning a new thread.
        self.thread_pool.idle_workers[self] = None
        self.thread_pool.release_full_lock()

        if isinstance(result, Error) and isinstance(result.error, _JobKill):
            pass
        else:
            with job.put_lock:
                job.queue.append(result)
                del job.worker
                job.notify_get.release()

    def _work(self) -> None:
        while True:
            if self.worker_lock.acquire(timeout=WorkerPool.IDLE_TIMEOUT):
                self._handle_job()
            else:
                # Timeout acquiring lock, so we can probably exit. But,
                # there's a race condition: we might be assigned a job *just*
                # as we're about to exit. So we have to check.
                try:
                    del self.thread_pool.idle_workers[self]
                except KeyError:
                    # Someone else removed us from the idle worker queue, so
                    # they must be in the process of assigning us a job - loop
                    # around and wait for it.
                    self.thread_pool.release_full_lock()
                    continue
                else:
                    # We successfully removed ourselves from the idle
                    # worker queue, so no more jobs are incoming; it's safe to
                    # exit.
                    del self.thread_pool.all_workers[self]
                    self.thread_pool.release_full_lock()
                    return

    def kill(self):
        """用异步异常终止阻塞线程，调用时必须持有 job.put_lock。

        返回异常是否成功注入。
        """
        ident = self.thread.ident
        if ident is None:
            logger.error(f"Failed to kill thread {ident} from job {self.job}")
            return False
        thread_id = ctypes.c_long(ident)
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, ctypes.py_object(_JobKill))
        if res <= 1:
            self.thread_pool.all_workers.pop(self, None)
            self.thread_pool.release_full_lock()
            return True
        try:
            job = self.job
        except AttributeError:
            job = None
        logger.error(f"Failed to kill thread {self.thread.ident} from job {job}")
        ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
        return False


class WorkerPool:
    """模仿 trio.to_thread.start_thread_soon() 的线程池。

    见 https://github.com/python-trio/trio/issues/6。
    """

    # 线程空闲 10 秒后退出。
    IDLE_TIMEOUT = 10

    def __init__(self, pool_size: int = 8):
        # 本地调用频率较低，默认使用小线程池。
        self.pool_size = pool_size

        self.idle_workers: dict[WorkerThread, None] = {}
        self.all_workers: dict[WorkerThread, None] = {}

        self.notify_worker = Lock()
        self.notify_worker.acquire()
        self.notify_pool = Lock()
        self.notify_pool.acquire()

    def release_full_lock(self):
        """工作线程完成、退出或被终止时释放池满等待。

        notify_worker 保证只有最快的一个线程通过 notify_pool 通知新槽位可用。
        """
        if self.notify_worker.acquire(blocking=False):
            self.notify_pool.release()

    def _get_thread_worker(self) -> WorkerThread:
        try:
            worker, _ = self.idle_workers.popitem()
        except KeyError:
            pass
        else:
            return worker

        if len(self.all_workers) >= self.pool_size:
            self.notify_worker.release()
            self.notify_pool.acquire()
            try:
                worker, _ = self.idle_workers.popitem()
            except KeyError:
                pass
            else:
                return worker

        worker = WorkerThread(self)
        self.all_workers[worker] = None
        return worker

    def start_thread_soon(self, func, *args, **kwargs):
        """在线程中调用 func，返回可取得结果或异常的 Job。"""
        worker = self._get_thread_worker()
        job = Job(worker=worker, func_args_kwargs=(func, args, kwargs))

        worker.job = job
        worker.worker_lock.release()
        return job

    def run_on_thread(self, func):
        """将函数包装为线程调用，每次调用返回 Job。"""

        @wraps(func)
        def thread_wrapper(*args, **kwargs) -> Job[ResultT]:
            return self.start_thread_soon(func, *args, **kwargs)

        return thread_wrapper

    def wait_jobs(self) -> WaitJobsWrapper:
        """上下文退出时等待其中所有 Job。"""
        return WaitJobsWrapper(self)

    def gather_jobs(self) -> GatherJobsWrapper:
        """上下文退出时等待所有 Job，并把结果收集到 results。"""
        return GatherJobsWrapper(self)

    def thread_map(self, func, iterables):
        jobs = [self.start_thread_soon(func, arg) for arg in iterables]
        return [job.get() for job in jobs]

    def thread_starmap(self, func, iterables):
        jobs = [self.start_thread_soon(func, *arg) for arg in iterables]
        return [job.get() for job in jobs]

    def thread_funcmap(self, func_iterables):
        jobs = [self.start_thread_soon(func) for func in func_iterables]
        return [job.get() for job in jobs]


class WaitJobsWrapper:
    def __init__(self, pool: WorkerPool):
        self.pool: WorkerPool = pool
        self.jobs: list[Job[object]] = []

    def get(self):
        for job in self.jobs:
            job.get()
        self.jobs.clear()

    def __enter__(self):
        self.jobs.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.get()

    def start_thread_soon(self, func, *args, **kwargs):
        job = self.pool.start_thread_soon(func, *args, **kwargs)
        self.jobs.append(job)
        return job


class GatherJobsWrapper(WaitJobsWrapper):
    def __init__(self, pool: WorkerPool):
        super().__init__(pool)
        self.results: list[object] = []

    def get(self):
        for job in self.jobs:
            result = job.get()
            self.results.append(result)
        self.jobs.clear()

    def __enter__(self):
        self.jobs.clear()
        self.results.clear()
        return self


WORKER_POOL = WorkerPool()
