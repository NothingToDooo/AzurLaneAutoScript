import queue
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing import Event, Process
from typing import TYPE_CHECKING, ClassVar

from rich.console import ConsoleRenderable

from module.application import Faulted
from module.bootstrap.process_host import InstanceProcessExit, InstanceProcessExitKind
from module.bootstrap.production import build_default_instance_process_host
from module.logger import logger, set_file_logger, set_func_logger
from module.task_registry import get_tool_task_command
from module.webui.fake_pil_module import remove_fake_pil_module
from module.webui.process_outcome import ProcessOutcome, ProcessOutcomeStatus
from module.webui.setting import State

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.stop_event import StopEvent

STOP_GRACE_SECONDS = 5
KILL_JOIN_SECONDS = 1
QUEUE_POLL_SECONDS = 0.1
QUEUE_DRAIN_SECONDS = 1
MONITOR_JOIN_SECONDS = 3
MAX_OUTCOME_MESSAGE_LENGTH = 500


type Renderable = ConsoleRenderable | str
type RenderableQueueItem = ConsoleRenderable | None


@dataclass(slots=True)
class _ProcessRun:
    command: str
    process: Process
    renderable_queue: queue.Queue[RenderableQueueItem]
    outcome_queue: queue.Queue[ProcessOutcome]
    stop_status: ProcessOutcomeStatus | None = None
    monitor: threading.Thread | None = None


def _short_message(error: BaseException) -> str:
    message = " ".join(str(error).splitlines()).strip() or type(error).__name__
    return message[:MAX_OUTCOME_MESSAGE_LENGTH]


def _new_outcome(
    status: ProcessOutcomeStatus,
    *,
    config_name: str,
    command: str,
    exception_type: str | None = None,
    message: str | None = None,
) -> ProcessOutcome:
    return ProcessOutcome(
        status=status,
        config_name=config_name,
        command=command,
        exception_type=exception_type,
        message=message,
        finished_at=datetime.now(UTC),
    )


def _fault_from_exit(exit_: InstanceProcessExit) -> Exception | None:
    result = exit_.task_result
    if result is None and exit_.loop_exit is not None:
        result = exit_.loop_exit.last_result
    if result is not None and isinstance(result.outcome, Faulted):
        return result.outcome.error
    return None


def _host_outcome(
    exit_: InstanceProcessExit,
    *,
    config_name: str,
    command: str,
) -> ProcessOutcome:
    if exit_.kind is InstanceProcessExitKind.FINISHED:
        status = ProcessOutcomeStatus.FINISHED
    elif exit_.kind is InstanceProcessExitKind.STOPPED:
        status = ProcessOutcomeStatus.MANUAL_STOP
    elif exit_.kind is InstanceProcessExitKind.RESTART_REQUESTED:
        status = ProcessOutcomeStatus.RESTART_REQUESTED
    else:
        error = _fault_from_exit(exit_)
        return _new_outcome(
            ProcessOutcomeStatus.FAILED,
            config_name=config_name,
            command=command,
            exception_type="InstanceRuntimeFailure" if error is None else type(error).__name__,
            message="instance runtime failed without a typed fault" if error is None else _short_message(error),
        )
    return _new_outcome(status, config_name=config_name, command=command)


def _execute_process(config_name: str, func: str, stop_event: StopEvent | None) -> ProcessOutcome:
    command = "alas" if func == "alas" else get_tool_task_command(func)
    if command is None:
        message = f"No function matched: {func}"
        logger.critical(message)
        return _new_outcome(
            ProcessOutcomeStatus.FAILED,
            config_name=config_name,
            command=func,
            exception_type="LookupError",
            message=message,
        )
    host = build_default_instance_process_host()
    exit_ = host.execute(config_name, command, stop_signal=stop_event)
    return _host_outcome(exit_, config_name=config_name, command=func)


def _system_exit_outcome(
    error: SystemExit,
    *,
    config_name: str,
    command: str,
    stop_event: StopEvent | None,
) -> ProcessOutcome:
    if stop_event is not None and stop_event.is_set():
        return _new_outcome(ProcessOutcomeStatus.MANUAL_STOP, config_name=config_name, command=command)
    if error.code in {None, 0}:
        return _new_outcome(ProcessOutcomeStatus.FINISHED, config_name=config_name, command=command)
    return _new_outcome(
        ProcessOutcomeStatus.FAILED,
        config_name=config_name,
        command=command,
        exception_type=type(error).__name__,
        message=_short_message(error),
    )


class ProcessManager:
    _processes: ClassVar[dict[str, ProcessManager]] = {}

    def __init__(self, config_name: str = "alas") -> None:
        self.config_name = config_name
        self.renderables: list[Renderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self._run: _ProcessRun | None = None
        self._stop_event: StopEvent | None = None
        self._lifecycle_lock = threading.Lock()
        self._outcome_lock = threading.Lock()
        self._outcome: ProcessOutcome | None = None
        self.thd_log_queue_handler: threading.Thread | None = None

    def start(self, func: str | None, ev: StopEvent | None = None) -> None:
        with self._lifecycle_lock:
            if self.alive:
                return
            self._join_monitor()
            command = "alas" if func is None else func
            renderable_queue: queue.Queue[RenderableQueueItem] = State.manager.Queue()
            outcome_queue: queue.Queue[ProcessOutcome] = State.manager.Queue()
            self._stop_event = Event() if ev is None else ev
            process = Process(
                target=ProcessManager.run_process,
                args=(
                    self.config_name,
                    command,
                    renderable_queue,
                    outcome_queue,
                    self._stop_event,
                ),
            )
            run = _ProcessRun(
                command=command,
                process=process,
                renderable_queue=renderable_queue,
                outcome_queue=outcome_queue,
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

    def start_log_queue_handler(self, run: _ProcessRun | None = None) -> None:
        if run is None:
            run = self._run
        if run is None:
            message = "Cannot start process monitor before a process run"
            raise RuntimeError(message)
        if run.monitor is not None and run.monitor.is_alive():
            return
        monitor = threading.Thread(target=self._thread_log_queue_handler, args=(run,))
        run.monitor = monitor
        if self._run is run:
            self.thd_log_queue_handler = monitor
        monitor.start()

    def _stop_process(self, run: _ProcessRun) -> None:
        process = run.process
        if not process.is_alive():
            return

        run.stop_status = ProcessOutcomeStatus.MANUAL_STOP
        if self._stop_event is not None:
            self._stop_event.set()
            process.join(timeout=STOP_GRACE_SECONDS)

        if process.is_alive():
            run.stop_status = ProcessOutcomeStatus.KILLED
            logger.warning(f"[{self.config_name}] did not stop gracefully, killing process")
            process.kill()
            process.join(timeout=KILL_JOIN_SECONDS)

    def stop(self) -> None:
        with self._lifecycle_lock:
            run = self._run
            if run is not None and run.process.is_alive():
                self._stop_process(run)
                if not run.process.is_alive():
                    self._stop_event = None
            self._join_monitor()
            if run is not None:
                self._publish_outcome(run, self._read_child_outcome(run, timeout=0))
        logger.info(f"[{self.config_name}] exited")

    def _append_renderable(self, renderable: ConsoleRenderable) -> None:
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
        outcome_timeout = 0 if run.stop_status is not None else QUEUE_DRAIN_SECONDS
        child_outcome = self._read_child_outcome(run, timeout=outcome_timeout)
        self._publish_outcome(run, child_outcome)
        logger.info("End of process monitor loop")

    @staticmethod
    def _read_child_outcome(run: _ProcessRun, *, timeout: float) -> ProcessOutcome | None:
        try:
            outcome = run.outcome_queue.get(timeout=timeout) if timeout else run.outcome_queue.get_nowait()
        except queue.Empty:
            return None
        while True:
            try:
                outcome = run.outcome_queue.get_nowait()
            except queue.Empty:
                return outcome

    def _publish_outcome(self, run: _ProcessRun, child_outcome: ProcessOutcome | None) -> None:
        with self._outcome_lock:
            if self._run is not run:
                return
            if run.stop_status is not None:
                self._outcome = _new_outcome(
                    run.stop_status,
                    config_name=self.config_name,
                    command=run.command,
                )
                return
            if child_outcome is not None:
                self._outcome = child_outcome
                return
            if self._outcome is not None:
                return
            exit_code = getattr(run.process, "exitcode", None)
            self._outcome = _new_outcome(
                ProcessOutcomeStatus.FAILED,
                config_name=self.config_name,
                command=run.command,
                exception_type="MissingProcessOutcome",
                message=f"Process exited without an outcome (exitcode={exit_code})",
            )

    @property
    def alive(self) -> bool:
        return self._run is not None and self._run.process.is_alive()

    @property
    def outcome(self) -> ProcessOutcome | None:
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
        if outcome.status in {ProcessOutcomeStatus.FAILED, ProcessOutcomeStatus.KILLED}:
            return 3
        return 2

    @classmethod
    def get_manager(cls, config_name: str) -> ProcessManager:
        if config_name not in cls._processes:
            cls._processes[config_name] = ProcessManager(config_name)
        return cls._processes[config_name]

    @staticmethod
    def run_process(
        config_name: str,
        func: str,
        renderable_queue: queue.Queue[RenderableQueueItem],
        outcome_queue: queue.Queue[ProcessOutcome],
        stop_event: StopEvent | None = None,
    ) -> None:
        outcome: ProcessOutcome | None = None
        try:
            set_file_logger(name=config_name)
            set_func_logger(func=renderable_queue.put)
            remove_fake_pil_module()
            outcome = _execute_process(config_name, func, stop_event)
        except SystemExit as error:
            outcome = _system_exit_outcome(
                error,
                config_name=config_name,
                command=func,
                stop_event=stop_event,
            )
            raise
        except Exception as error:  # noqa: BLE001
            logger.exception(error)
            outcome = _new_outcome(
                ProcessOutcomeStatus.FAILED,
                config_name=config_name,
                command=func,
                exception_type=type(error).__name__,
                message=_short_message(error),
            )
        finally:
            if outcome is None:
                outcome = _new_outcome(
                    ProcessOutcomeStatus.FAILED,
                    config_name=config_name,
                    command=func,
                    exception_type="ProcessExit",
                    message="Process exited before producing an outcome",
                )
            logger.info(f"[{config_name}] exited. Reason: {outcome.status.value}\n")
            try:
                outcome_queue.put(outcome)
            finally:
                renderable_queue.put(None)

    @classmethod
    def running_instances(cls) -> list[ProcessManager]:
        return [process for process in cls._processes.values() if process.alive]

    @classmethod
    def stop_all(cls) -> None:
        for process in cls._processes.values():
            process.stop()

    @staticmethod
    def restart_processes(
        instances: Sequence[ProcessManager | str] | None = None,
        ev: StopEvent | None = None,
    ) -> None:
        logger.hr("Restart alas")
        if instances is None:
            instances = []

        resolved_instances: set[ProcessManager] = set()
        for instance in instances:
            if isinstance(instance, str):
                resolved_instances.add(ProcessManager.get_manager(instance))
            elif isinstance(instance, ProcessManager):
                resolved_instances.add(instance)

        for process in resolved_instances:
            logger.info(f"Starting [{process.config_name}]")
            process.start(func="alas", ev=ev)

        logger.info("Start alas complete")
