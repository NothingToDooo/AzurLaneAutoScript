import multiprocessing
import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from os import chdir
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self, cast

from rich.console import ConsoleRenderable

from module.logger import configure_file_logging, logger, set_func_logger
from module.runtime.runner import CommandOutcome, CommandStatus
from module.task_registry import get_tool_task_command

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.process import BaseProcess
    from multiprocessing.queues import Queue as ProcessQueue

    from module.base.stop_event import StopEvent

KILL_JOIN_SECONDS = 1
QUEUE_POLL_SECONDS = 0.1
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUEUE_DRAIN_SECONDS = 1
MONITOR_JOIN_SECONDS = 3
MAX_OUTCOME_MESSAGE_LENGTH = 500


type Renderable = ConsoleRenderable | str
type RenderableQueueItem = Renderable | None


@dataclass(frozen=True, slots=True)
class _ProcessRequest:
    """可跨 spawn 边界传递的纯业务请求。"""

    command: str


@dataclass(slots=True)
class _ProcessRun:
    command: str
    process: BaseProcess
    renderable_queue: ProcessQueue[RenderableQueueItem]
    outcome_queue: ProcessQueue[CommandOutcome]
    stop_event: StopEvent
    stop_requested: bool = False
    forced: bool = False
    monitor: threading.Thread | None = None


def _short_message(error: BaseException) -> str:
    message = " ".join(str(error).splitlines()).strip() or type(error).__name__
    return message[:MAX_OUTCOME_MESSAGE_LENGTH]


def _new_outcome(
    status: CommandStatus,
    *,
    command: str,
    exception_type: str | None = None,
    message: str | None = None,
) -> CommandOutcome:
    return CommandOutcome(
        status=status,
        command=command,
        exception_type=exception_type,
        message=message,
        finished_at=datetime.now(UTC),
    )


def _execute_process(
    request: _ProcessRequest,
    stop_event: StopEvent | None,
) -> CommandOutcome:
    resolved_command = "alas" if request.command == "alas" else get_tool_task_command(request.command)
    if resolved_command is None:
        message = f"No function matched: {request.command}"
        logger.critical(message)
        return _new_outcome(
            CommandStatus.FAILED,
            command=request.command,
            exception_type="LookupError",
            message=message,
        )
    # production 依赖只在实际 worker 执行有效命令时加载。
    from module.bootstrap.production import run_default_command  # ruff:ignore[import-outside-top-level]

    return run_default_command(resolved_command, stop_signal=stop_event)


def _system_exit_outcome(
    error: SystemExit,
    *,
    command: str,
    stop_event: StopEvent | None,
) -> CommandOutcome:
    if stop_event is not None and stop_event.is_set():
        return _new_outcome(CommandStatus.STOPPED, command=command)
    if error.code in {None, 0}:
        return _new_outcome(CommandStatus.FINISHED, command=command)
    return _new_outcome(
        CommandStatus.FAILED,
        command=command,
        exception_type=type(error).__name__,
        message=_short_message(error),
    )


class ProcessManager:
    _singleton: ClassVar[ProcessManager | None] = None

    def __new__(cls) -> Self:
        if cls._singleton is None:
            cls._singleton = super().__new__(cls)
        return cast("Self", cls._singleton)

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.renderables: list[Renderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self._run: _ProcessRun | None = None
        self._start_inhibitors = 0
        self._lifecycle_lock = threading.Lock()
        self._outcome_lock = threading.Lock()
        self._outcome: CommandOutcome | None = None
        self.thd_log_queue_handler: threading.Thread | None = None

    @classmethod
    def instance(cls) -> ProcessManager:
        return cls()

    def start_default(self) -> None:
        self.start("alas")

    def start(self, command: str) -> None:
        if not isinstance(command, str) or not command or command != command.strip():
            message = "command must be trimmed and non-empty"
            raise ValueError(message)
        with self._lifecycle_lock:
            if self._start_inhibitors or self.alive:
                return
            self._join_monitor()
            request = _ProcessRequest(command)
            process_context = multiprocessing.get_context("spawn")
            renderable_queue: ProcessQueue[RenderableQueueItem] = process_context.Queue()
            outcome_queue: ProcessQueue[CommandOutcome] = process_context.Queue()
            stop_event = process_context.Event()
            process = process_context.Process(
                target=ProcessManager.run_process,
                args=(request, renderable_queue, outcome_queue, stop_event),
            )
            run = _ProcessRun(
                command=command,
                process=process,
                renderable_queue=renderable_queue,
                outcome_queue=outcome_queue,
                stop_event=stop_event,
            )
            self._run = run
            with self._outcome_lock:
                self._outcome = None
            process.start()
            self.start_log_queue_handler(run)

    def _join_monitor(self) -> None:
        monitor = self.thd_log_queue_handler
        if monitor is None or not monitor.is_alive():
            return
        monitor.join(timeout=MONITOR_JOIN_SECONDS)
        if monitor.is_alive():
            logger.warning("Process monitor is still draining its queue")

    def start_log_queue_handler(self, run: _ProcessRun) -> None:
        if run.monitor is not None and run.monitor.is_alive():
            return
        monitor = threading.Thread(target=self._thread_log_queue_handler, args=(run,))
        run.monitor = monitor
        if self._run is run:
            self.thd_log_queue_handler = monitor
        monitor.start()

    def _request_stop(self, run: _ProcessRun) -> None:
        with self._outcome_lock:
            if run.stop_requested:
                return
            run.stop_event.set()
            run.stop_requested = True

    def request_stop(self) -> None:
        with self._lifecycle_lock:
            run = self._run
            if run is not None and run.process.is_alive():
                self._request_stop(run)

    @contextmanager
    def hold_start(self) -> Iterator[None]:
        """在调用方完成一次状态替换前禁止启动新子进程。"""

        with self._lifecycle_lock:
            self._start_inhibitors += 1
        try:
            yield
        finally:
            with self._lifecycle_lock:
                self._start_inhibitors -= 1

    def stop_and_wait(self) -> None:
        with self.hold_start():
            with self._lifecycle_lock:
                run = self._run
                if run is not None and run.process.is_alive():
                    self._request_stop(run)

            # 等待期间不持有 lifecycle lock，显式 force_stop 必须始终可用。
            if run is not None and run.process.is_alive():
                run.process.join()

            with self._lifecycle_lock:
                self._join_monitor()
                if run is not None:
                    outcome_timeout = 0 if run.forced else QUEUE_DRAIN_SECONDS
                    child_outcome = self._read_child_outcome(run, timeout=outcome_timeout)
                    self._publish_outcome(run, child_outcome)
        logger.info("[alas] exited")

    def force_stop(self) -> None:
        with self._lifecycle_lock:
            run = self._run
            if run is not None and run.process.is_alive():
                self._request_stop(run)
                logger.warning("[alas] force killing process")
                run.process.kill()
                run.forced = True

        if run is not None and run.forced:
            run.process.join(timeout=KILL_JOIN_SECONDS)
            if run.process.is_alive():
                message = "[alas] process is still alive after kill"
                raise RuntimeError(message)

        with self._lifecycle_lock:
            self._join_monitor()
            if run is not None:
                outcome_timeout = 0 if run.forced else QUEUE_DRAIN_SECONDS
                child_outcome = self._read_child_outcome(run, timeout=outcome_timeout)
                self._publish_outcome(run, child_outcome)
        logger.info("[alas] exited")

    def _append_renderable(self, renderable: Renderable) -> None:
        self.renderables.append(renderable)
        if len(self.renderables) > self.renderables_max_length:
            self.renderables = self.renderables[self.renderables_reduce_length :]

    def _thread_log_queue_handler(self, run: _ProcessRun) -> None:
        stopped_deadline: float | None = None
        while True:
            try:
                renderable = run.renderable_queue.get(timeout=QUEUE_POLL_SECONDS)
            except queue.Empty:
                if run.process.is_alive():
                    stopped_deadline = None
                    continue
                if stopped_deadline is None:
                    stopped_deadline = time.monotonic() + QUEUE_DRAIN_SECONDS
                if time.monotonic() < stopped_deadline:
                    continue
                break
            if renderable is None:
                break
            self._append_renderable(renderable)

        run.process.join(timeout=KILL_JOIN_SECONDS)
        outcome_timeout = 0 if run.forced else QUEUE_DRAIN_SECONDS
        child_outcome = self._read_child_outcome(run, timeout=outcome_timeout)
        self._publish_outcome(run, child_outcome)
        logger.info("End of process monitor loop")

    @staticmethod
    def _read_child_outcome(run: _ProcessRun, *, timeout: float) -> CommandOutcome | None:
        try:
            outcome = run.outcome_queue.get(timeout=timeout) if timeout else run.outcome_queue.get_nowait()
        except queue.Empty:
            return None
        while True:
            try:
                outcome = run.outcome_queue.get_nowait()
            except queue.Empty:
                return outcome

    def _publish_outcome(self, run: _ProcessRun, child_outcome: CommandOutcome | None) -> None:
        with self._outcome_lock:
            if self._run is not run:
                return
            if run.forced:
                self._outcome = _new_outcome(CommandStatus.KILLED, command=run.command)
                return
            if child_outcome is not None:
                self._outcome = (
                    replace(child_outcome, status=CommandStatus.STOPPED)
                    if run.stop_requested and child_outcome.status is CommandStatus.FINISHED
                    else child_outcome
                )
                return
            if self._outcome is not None:
                return
            exit_code = getattr(run.process, "exitcode", None)
            self._outcome = _new_outcome(
                CommandStatus.FAILED,
                command=run.command,
                exception_type="MissingProcessOutcome",
                message=f"Process exited without an outcome (exitcode={exit_code})",
            )

    @property
    def alive(self) -> bool:
        return self._run is not None and self._run.process.is_alive()

    @property
    def outcome(self) -> CommandOutcome | None:
        run = self._run
        if run is not None:
            child_outcome = self._read_child_outcome(run, timeout=0)
            if child_outcome is not None:
                self._publish_outcome(run, child_outcome)
        with self._outcome_lock:
            return self._outcome

    @property
    def state(self) -> int:
        if self.alive:
            return 1
        outcome = self.outcome
        if outcome is None:
            return 2 if self._run is None else 3
        if outcome.status in {CommandStatus.FAILED, CommandStatus.KILLED}:
            return 3
        return 2

    @staticmethod
    def run_process(
        request: _ProcessRequest,
        renderable_queue: queue.Queue[RenderableQueueItem],
        outcome_queue: queue.Queue[CommandOutcome],
        stop_event: StopEvent | None = None,
    ) -> None:
        outcome: CommandOutcome | None = None
        try:
            chdir(PROJECT_ROOT)
            configure_file_logging(PROJECT_ROOT, name="alas")
            set_func_logger(func=renderable_queue.put)
            outcome = _execute_process(request, stop_event)
        except SystemExit as error:
            outcome = _system_exit_outcome(
                error,
                command=request.command,
                stop_event=stop_event,
            )
            raise
        except BaseExceptionGroup as error:
            logger.exception(error)
            outcome = _new_outcome(
                CommandStatus.FAILED,
                command=request.command,
                exception_type=type(error).__name__,
                message=_short_message(error),
            )
            raise
        except Exception as error:  # ruff:ignore[blind-except] - 子进程边界必须返回可序列化结果。
            logger.exception(error)
            outcome = _new_outcome(
                CommandStatus.FAILED,
                command=request.command,
                exception_type=type(error).__name__,
                message=_short_message(error),
            )
        finally:
            if outcome is None:
                outcome = _new_outcome(
                    CommandStatus.FAILED,
                    command=request.command,
                    exception_type="ProcessExit",
                    message="Process exited before producing an outcome",
                )
            logger.info(f"[alas] exited. Reason: {outcome.status.value}\n")
            try:
                outcome_queue.put(outcome)
            finally:
                renderable_queue.put(None)

    @classmethod
    def force_stop_instance(cls) -> None:
        if cls._singleton is not None:
            cls._singleton.force_stop()
