import queue
import threading
from multiprocessing import Event, Process
from typing import TYPE_CHECKING, ClassVar, cast

from rich.console import Console, ConsoleRenderable

from alas import AzurLaneAutoScript
from module.config.config import AzurLaneConfig
from module.logger import logger, set_file_logger, set_func_logger
from module.task_registry import get_direct_task_command
from module.webui.fake_pil_module import remove_fake_pil_module
from module.webui.setting import State

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.stop_event import StopEvent

STOP_GRACE_SECONDS = 5
KILL_JOIN_SECONDS = 1


class ProcessManager:
    _processes: ClassVar[dict[str, ProcessManager]] = {}

    def __init__(self, config_name: str = "alas") -> None:
        self.config_name = config_name
        self._renderable_queue: queue.Queue[ConsoleRenderable] = State.manager.Queue()
        self.renderables: list[ConsoleRenderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self._process: Process | None = None
        self._stop_event: StopEvent | None = None
        self._stop_lock = threading.Lock()
        self.thd_log_queue_handler: threading.Thread | None = None

    def start(self, func: str | None, ev: StopEvent | None = None) -> None:
        if not self.alive:
            if func is None:
                func = "alas"
            self._stop_event = Event() if ev is None else ev
            self._process = Process(
                target=ProcessManager.run_process,
                args=(
                    self.config_name,
                    func,
                    self._renderable_queue,
                    self._stop_event,
                ),
            )
            self._process.start()
            self.start_log_queue_handler()

    def start_log_queue_handler(self):
        if self.thd_log_queue_handler is not None and self.thd_log_queue_handler.is_alive():
            return
        self.thd_log_queue_handler = threading.Thread(target=self._thread_log_queue_handler)
        self.thd_log_queue_handler.start()

    def _stop_process(self) -> None:
        process = self._process
        if process is None or not process.is_alive():
            return

        if self._stop_event is not None:
            self._stop_event.set()
            process.join(timeout=STOP_GRACE_SECONDS)

        if process.is_alive():
            logger.warning(f"[{self.config_name}] did not stop gracefully, killing process")
            process.kill()
            process.join(timeout=KILL_JOIN_SECONDS)

        self.renderables.append(cast("ConsoleRenderable", f"[{self.config_name}] exited. Reason: Manual stop\n"))

    def stop(self) -> None:
        with self._stop_lock:
            if self.alive:
                self._stop_process()
                if self._process is not None and not self._process.is_alive():
                    self._stop_event = None
            if self.thd_log_queue_handler is not None:
                self.thd_log_queue_handler.join(timeout=1)
                if self.thd_log_queue_handler.is_alive():
                    logger.warning("Log queue handler thread does not stop within 1 seconds")
        logger.info(f"[{self.config_name}] exited")

    def _thread_log_queue_handler(self) -> None:
        while self.alive:
            try:
                log = self._renderable_queue.get(timeout=1)
            except queue.Empty:
                continue
            self.renderables.append(log)
            if len(self.renderables) > self.renderables_max_length:
                self.renderables = self.renderables[self.renderables_reduce_length :]
        logger.info("End of log queue handler loop")

    @property
    def alive(self) -> bool:
        if self._process is not None:
            return self._process.is_alive()
        return False

    @property
    def state(self) -> int:
        if self.alive:
            return 1
        if len(self.renderables) == 0:
            return 2
        console = Console(no_color=True)
        with console.capture() as capture:
            console.print(self.renderables[-1])
        s = capture.get().strip()
        if s.endswith(("Reason: Manual stop", "Reason: Finish")):
            return 2
        return 3

    @classmethod
    def get_manager(cls, config_name: str) -> ProcessManager:
        if config_name not in cls._processes:
            cls._processes[config_name] = ProcessManager(config_name)
        return cls._processes[config_name]

    @staticmethod
    def run_process(config_name, func: str, q: queue.Queue, stop_event: StopEvent | None = None) -> None:
        set_file_logger(name=config_name)
        set_func_logger(func=q.put)

        # 子进程会使用真实 PIL，需要移除 WebUI 进程里的伪模块。
        remove_fake_pil_module()

        AzurLaneConfig.stop_event = stop_event
        try:
            if func == "alas":
                if stop_event is not None:
                    AzurLaneAutoScript.stop_event = stop_event
                AzurLaneAutoScript(config_name=config_name).loop()
            else:
                command = get_direct_task_command(func)
                if command is None:
                    logger.critical(f"No function matched: {func}")
                else:
                    AzurLaneAutoScript(config_name=config_name).run(command, skip_first_screenshot=True)
            logger.info(f"[{config_name}] exited. Reason: Finish\n")
        # WebUI 子进程边界：把未知异常写入 renderable 队列，否则页面看不到堆栈。
        except Exception as error:  # noqa: BLE001
            logger.exception(error)

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

        resolved_instances = set()

        for instance in instances:
            if isinstance(instance, str):
                resolved_instances.add(ProcessManager.get_manager(instance))
            elif isinstance(instance, ProcessManager):
                resolved_instances.add(instance)

        for process in resolved_instances:
            logger.info(f"Starting [{process.config_name}]")
            process.start(func="alas", ev=ev)

        logger.info("Start alas complete")
