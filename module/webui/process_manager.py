import queue
import threading
from multiprocessing import Process
from typing import TYPE_CHECKING, ClassVar, cast

from rich.console import Console, ConsoleRenderable

if TYPE_CHECKING:
    from collections.abc import Sequence

# 这个文件不会运行在 app.py 的同一进程或子进程中，下面的初始化需要重复执行。
# 先导入伪 PIL 模块，避免 pywebio 拉起不需要的 PIL。
from module.webui.fake_pil_module import import_fake_pil_module, remove_fake_pil_module

import_fake_pil_module()

from alas import AzurLaneAutoScript
from module.base.naming import camel_to_snake
from module.config.config import AzurLaneConfig
from module.logger import logger, set_file_logger, set_func_logger
from module.submodule.submodule import load_mod
from module.submodule.utils import (
    get_available_func,
    get_available_mod,
    get_available_mod_func,
    get_config_mod,
    get_func_mod,
    list_mod_instance,
)
from module.webui.setting import State


class ProcessManager:
    _processes: ClassVar[dict[str, ProcessManager]] = {}

    def __init__(self, config_name: str = "alas") -> None:
        self.config_name = config_name
        self._renderable_queue: queue.Queue[ConsoleRenderable] = State.manager.Queue()
        self.renderables: list[ConsoleRenderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self._process: Process | None = None
        self._process_locks: dict[str, threading.Lock] = {}
        self.thd_log_queue_handler: threading.Thread | None = None

    def start(self, func, ev: threading.Event | None = None) -> None:
        if not self.alive:
            if func is None:
                func = get_config_mod(self.config_name)
            self._process = Process(
                target=ProcessManager.run_process,
                args=(
                    self.config_name,
                    func,
                    self._renderable_queue,
                    ev,
                ),
            )
            self._process.start()
            self.start_log_queue_handler()

    def start_log_queue_handler(self):
        if self.thd_log_queue_handler is not None and self.thd_log_queue_handler.is_alive():
            return
        self.thd_log_queue_handler = threading.Thread(target=self._thread_log_queue_handler)
        self.thd_log_queue_handler.start()

    def stop(self) -> None:
        try:
            lock = self._process_locks[self.config_name]
        except KeyError:
            lock = threading.Lock()
            self._process_locks[self.config_name] = lock

        with lock:
            if self.alive:
                process = self._process
                if process is not None:
                    process.kill()
                self.renderables.append(cast("ConsoleRenderable", f"[{self.config_name}] exited. Reason: Manual stop\n"))
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
        """
        Create a new alas if not exists.
        """
        if config_name not in cls._processes:
            cls._processes[config_name] = ProcessManager(config_name)
        return cls._processes[config_name]

    @staticmethod
    def run_process(config_name, func: str, q: queue.Queue, stop_event: threading.Event | None = None) -> None:
        # 初始化子进程 logger。
        set_file_logger(name=config_name)
        set_func_logger(func=q.put)

        # 子进程会使用真实 PIL，需要移除 WebUI 进程里的伪模块。
        remove_fake_pil_module()

        AzurLaneConfig.stop_event = cast("threading.Event", stop_event)
        try:
            # 运行指定入口。
            if func == "alas":
                if stop_event is not None:
                    AzurLaneAutoScript.stop_event = stop_event
                AzurLaneAutoScript(config_name=config_name).loop()
            elif func in get_available_func():
                AzurLaneAutoScript(config_name=config_name).run(camel_to_snake(func), skip_first_screenshot=True)
            elif func in get_available_mod():
                mod = load_mod(func)

                if stop_event is not None:
                    mod.set_stop_event(stop_event)
                mod.loop(config_name)
            elif func in get_available_mod_func():
                getattr(load_mod(get_func_mod(func)), camel_to_snake(func))(config_name)
            else:
                logger.critical(f"No function matched: {func}")
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
        ev: threading.Event | None = None,
    ) -> None:
        """
        Start configured alas instances when the web service starts.
        """
        logger.hr("Restart alas")

        # Load MOD_CONFIG_DICT
        list_mod_instance()

        if instances is None:
            instances = []

        _instances = set()

        for instance in instances:
            if isinstance(instance, str):
                _instances.add(ProcessManager.get_manager(instance))
            elif isinstance(instance, ProcessManager):
                _instances.add(instance)

        for process in _instances:
            logger.info(f"Starting [{process.config_name}]")
            process.start(func=get_config_mod(process.config_name), ev=ev)

        logger.info("Start alas complete")
