import datetime
import operator
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TypeIs

import pywebio
from pywebio.exceptions import SessionException
from pywebio.input import PASSWORD
from pywebio.input import input as pywebio_input
from pywebio.output import PopupSize, popup, put_html, toast
from pywebio.session import eval_js, register_thread, run_js
from rich.console import Console
from rich.terminal_theme import TerminalTheme

from module.config.deep import DeepValue, MutableDeepValue, deep_iter
from module.logger import logger
from module.webui.setting import State

if TYPE_CHECKING:
    from queue import Queue

    from pywebio.session.base import Session

RE_DATETIME = (
    r"\d{4}\-(0\d|1[0-2])\-([0-2]\d|[3][0-1]) "
    r"([0-1]\d|[2][0-3]):([0-5]\d):([0-5]\d)"
)


TRACEBACK_CODE_FORMAT = """\
<code class="rich-traceback">
    <pre class="rich-traceback-code">{code}</pre>
</code>
"""

LOG_CODE_FORMAT = "{code}"

DARK_TERMINAL_THEME = TerminalTheme(
    (30, 30, 30),  # Background
    (204, 204, 204),  # Foreground
    [
        (0, 0, 0),  # Black
        (205, 49, 49),  # Red
        (13, 188, 121),  # Green
        (229, 229, 16),  # Yellow
        (36, 114, 200),  # Blue
        (188, 63, 188),  # Purple / Magenta
        (17, 168, 205),  # Cyan
        (229, 229, 229),  # White
    ],
    [  # Bright
        (102, 102, 102),  # Black
        (241, 76, 76),  # Red
        (35, 209, 139),  # Green
        (245, 245, 67),  # Yellow
        (59, 142, 234),  # Blue
        (214, 112, 214),  # Purple / Magenta
        (41, 184, 219),  # Cyan
        (229, 229, 229),  # White
    ],
)

LIGHT_TERMINAL_THEME = TerminalTheme(
    (255, 255, 255),  # Background
    (97, 97, 97),  # Foreground
    [
        (0, 0, 0),  # Black
        (205, 49, 49),  # Red
        (0, 188, 0),  # Green
        (148, 152, 0),  # Yellow
        (4, 81, 165),  # Blue
        (188, 5, 188),  # Purple / Magenta
        (5, 152, 188),  # Cyan
        (85, 85, 85),  # White
    ],
    [  # Bright
        (102, 102, 102),  # Black
        (205, 49, 49),  # Red
        (20, 206, 20),  # Green
        (181, 186, 0),  # Yellow
        (4, 81, 165),  # Blue
        (188, 5, 188),  # Purple / Magenta
        (5, 152, 188),  # Cyan
        (165, 165, 165),  # White
    ],
)


class QueueHandler:
    def __init__(self, q: Queue[str]) -> None:
        self.queue = q

    def write(self, s: str) -> None:
        self.queue.put(s)


type TaskGenerator = Generator[None, TaskHandler | None]


def _is_task_generator(value: Callable[[], None] | TaskGenerator) -> TypeIs[TaskGenerator]:
    return isinstance(value, Generator)


class Task:
    def __init__(
        self,
        g: TaskGenerator,
        delay: float,
        next_run: float | None = None,
        name: str | None = None,
    ) -> None:
        self.g = g
        g.send(None)
        self.delay = delay
        self.next_run = next_run if next_run is not None else time.time()
        self.name = name if name is not None else getattr(self.g, "__name__", type(self.g).__name__)

    def __str__(self) -> str:
        return f"<{self.name} (delay={self.delay})>"

    def __next__(self) -> None:
        return next(self.g)

    def send(self, obj: TaskHandler | None) -> None:
        return self.g.send(obj)

    __repr__ = __str__


class TaskHandler:
    def __init__(self) -> None:
        self.tasks: list[Task] = []
        self.pending_remove_tasks: list[Task] = []
        self._task: Task | None = None
        self._thread: threading.Thread | None = None
        self._alive = False
        self._lock = threading.Lock()

    def add(
        self,
        func: Callable[[], None] | TaskGenerator,
        delay: float,
        *,
        pending_delete: bool = False,
    ) -> None:
        g = func if _is_task_generator(func) else get_generator(func)
        self.add_task(Task(g, delay), pending_delete=pending_delete)

    def add_task(self, task: Task, *, pending_delete: bool = False) -> None:
        if task in self.tasks:
            logger.warning(f"Task {task} already in tasks list.")
            return
        logger.info(f"Add task {task}")
        with self._lock:
            self.tasks.append(task)
        if pending_delete:
            self.pending_remove_tasks.append(task)

    def _remove_task(self, task: Task) -> None:
        if task in self.tasks:
            self.tasks.remove(task)
            logger.info(f"Task {task} removed.")
        else:
            logger.warning(f"Failed to remove task {task}. Current tasks list: {self.tasks}")

    def remove_task(self, task: Task, *, nowait: bool = False) -> None:
        """默认延迟删除；nowait=True 时立即从任务列表移除。"""
        if nowait:
            with self._lock:
                self._remove_task(task)
        else:
            self.pending_remove_tasks.append(task)

    def remove_pending_task(self) -> None:
        with self._lock:
            for task in self.pending_remove_tasks:
                self._remove_task(task)
            self.pending_remove_tasks = []

    def remove_current_task(self) -> None:
        if self._task is not None:
            self.remove_task(self._task, nowait=True)

    def set_current_task_delay(self, delay: float) -> None:
        if self._task is not None:
            self._task.delay = delay

    def get_task(self, name: str) -> Task | None:
        with self._lock:
            for task in self.tasks:
                if task.name == name:
                    return task
            return None

    def loop(self) -> None:
        """在独立线程中运行后台任务调度循环。"""
        self._alive = True
        while self._alive:
            if self.tasks:
                with self._lock:
                    self.tasks.sort(key=operator.attrgetter("next_run"))
                    task = self.tasks[0]
                if task.next_run < time.time():
                    start_time = time.time()
                    try:
                        self._task = task
                        task.send(self)
                    except StopIteration:
                        logger.info(f"Task {task} finished")
                        self.remove_task(task, nowait=True)
                    except SessionException as e:
                        logger.warning(e)
                        self.remove_task(task, nowait=True)
                    finally:
                        self._task = None
                    end_time = time.time()
                    task.next_run += task.delay
                    with self._lock:
                        for task in self.tasks:
                            task.next_run += end_time - start_time
                else:
                    time.sleep(0.05)
            else:
                time.sleep(0.5)
        logger.info("End of task handler loop")

    def _get_thread(self) -> threading.Thread:
        return threading.Thread(target=self.loop, daemon=True)

    def start(self) -> None:
        logger.info("Start task handler")
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Task handler already running!")
            return
        self._thread = self._get_thread()
        self._thread.start()

    def stop(self) -> None:
        self.remove_pending_task()
        self._alive = False
        thread = self._thread
        if thread is None:
            return
        thread.join(timeout=2)
        if not thread.is_alive():
            logger.info("Finish task handler")
        else:
            logger.warning("Task handler does not stop within 2 seconds")


class WebIOTaskHandler(TaskHandler):
    def _get_thread(self) -> threading.Thread:
        thread = super()._get_thread()
        register_thread(thread)
        return thread


type SwitchState = int
type SwitchAction = Callable[[], None]
type SwitchStatus = Callable[[SwitchState], None] | Mapping[SwitchState, SwitchAction | Sequence[SwitchAction]]
type SwitchStateSource = Callable[[], SwitchState] | Generator[SwitchState]


def _is_state_generator(value: SwitchStateSource) -> TypeIs[Generator[SwitchState]]:
    return isinstance(value, Generator)


def _is_action_sequence(value: SwitchAction | Sequence[SwitchAction]) -> TypeIs[Sequence[SwitchAction]]:
    return isinstance(value, Sequence)


def _is_status_mapping(
    value: SwitchStatus,
) -> TypeIs[Mapping[SwitchState, SwitchAction | Sequence[SwitchAction]]]:
    return isinstance(value, Mapping)


class Switch:
    def __init__(
        self,
        status: SwitchStatus,
        get_state: SwitchStateSource,
        name: str | None = None,
    ) -> None:
        """status 可为状态回调，或状态到回调／任务字典列表的映射。
        get_state 可为返回当前状态的回调或逐次产出状态的生成器。
        """
        self._lock = threading.Lock()
        self.name = name
        self.status = status
        self._generator: Generator[SwitchState]
        if _is_state_generator(get_state):
            self._generator = get_state
            self._get_state_callback: Callable[[], SwitchState] | None = None
        else:
            self._get_state_callback = get_state
            self._generator = self._state_changes()

    def _state_changes(self) -> Generator[SwitchState]:
        """仅在回调结果变化时产出新状态，否则产出 -1。"""
        get_state = self._get_state_callback
        if get_state is None:
            message = "state callback is unavailable for generator-backed switches"
            raise RuntimeError(message)
        previous_status = get_state()
        yield previous_status
        while True:
            status = get_state()
            if previous_status != status:
                previous_status = status
                yield previous_status
                continue
            yield -1

    def switch(self) -> None:
        with self._lock:
            state = next(self._generator)
        status = self.status
        if _is_status_mapping(status):
            if state not in status:
                return
            actions = status[state]
            if not _is_action_sequence(actions):
                actions = (actions,)
            for action in actions:
                action()
            return
        status(state)

    def g(self) -> TaskGenerator:
        g = get_generator(self.switch)
        state_source = self._get_state_callback or self._generator
        self.name = self.name or getattr(state_source, "__name__", type(state_source).__name__)
        return g


def get_generator(func: Callable[[], None]) -> TaskGenerator:
    def _g() -> TaskGenerator:
        yield
        while True:
            yield func()

    return _g()


def filepath_css(filename: str) -> str:
    return f"./assets/gui/css/{filename}.css"


def filepath_icon(filename: str) -> str:
    return f"./assets/gui/icon/{filename}.svg"


def add_css(filepath: str | Path) -> None:
    css = Path(filepath).read_text(encoding="utf-8").replace("\n", "")
    run_js(f"""$('head').append('<style>{css}</style>')""")


def _read(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


class Icon:
    ALAS = _read(filepath_icon("alas"))
    SETTING = _read(filepath_icon("setting"))
    RUN = _read(filepath_icon("run"))
    DEVELOP = _read(filepath_icon("develop"))
    ADD = _read(filepath_icon("add"))


def _parse_typed_pin_value(val: MutableDeepValue, valuetype: str) -> MutableDeepValue:
    if valuetype == "str":
        return str(val)
    if valuetype == "float":
        return float(str(val))
    if valuetype == "int":
        return int(str(val))
    if valuetype == "bool":
        return bool(val)
    if valuetype == "ignore":
        return val
    raise KeyError(valuetype)


def parse_pin_value(val: MutableDeepValue, valuetype: str | None = None) -> MutableDeepValue:
    """
    input、textarea 返回 str。
    select 返回选项值（str 或 int）。
    checkbox 返回 [] 或 [True]（由 put_checkbox_ 定义）。
    """
    if isinstance(val, list):
        return bool(val)
    if valuetype is not None:
        return _parse_typed_pin_value(val, valuetype)
    if not isinstance(val, str):
        return val
    try:
        v = float(val)
    except ValueError:
        return val
    return int(v) if v.is_integer() else v


def to_pin_value(val: MutableDeepValue) -> MutableDeepValue:
    """把 bool 转为 PyWebIO checkbox 使用的列表值。"""
    if val is True:
        return [True]
    if val is False:
        return []
    return val


def login(password: str) -> bool:
    if get_localstorage("password") == str(password):
        return True
    pwd = pywebio_input(label="Please login below.", type=PASSWORD, placeholder="PASSWORD")
    if str(pwd) == str(password):
        set_localstorage("password", str(pwd))
        return True
    toast("Wrong password!", color="error")
    return False


def get_window_visibility_state() -> bool:
    ret = eval_js("document.visibilityState")
    return ret != "hidden"


# https://pywebio.readthedocs.io/zh_CN/latest/cookbook.html#cookie-and-localstorage-manipulation
def set_localstorage(key: str, value: str) -> None:
    run_js("localStorage.setItem(key, value)", key=key, value=value)


def get_localstorage(key: str) -> str | None:
    value = eval_js("localStorage.getItem(key)", key=key)
    if value is None or isinstance(value, str):
        return value
    message = f"localStorage value for {key} must be a string"
    raise TypeError(message)


def re_fullmatch(pattern: str, string: str) -> bool:
    if pattern == "datetime":
        try:
            datetime.datetime.fromisoformat(string)
        except ValueError:
            return False
        else:
            return True
    return re.fullmatch(pattern=pattern, string=string) is not None


def get_next_time(t: datetime.time) -> int:
    now = datetime.datetime.now(tz=datetime.UTC).astimezone().time()
    second = (t.hour - now.hour) * 3600 + (t.minute - now.minute) * 60 + (t.second - now.second)
    if second < 0:
        second += 86400
    return second


def on_task_exception(self: Session) -> None:
    del self
    logger.exception("An internal error occurred in the application")
    toast_msg = "应用发生内部错误"

    e_type, e_value, e_tb = sys.exc_info()
    lines = traceback.format_exception(e_type, e_value, e_tb)
    traceback_msg = "".join(lines)

    traceback_console = Console(color_system="truecolor", tab_size=2, record=True, width=90)
    with traceback_console.capture():  # 避免再次输出到 stdout。
        traceback_console.print_exception(word_wrap=True, extra_lines=1, show_locals=True)

    theme = DARK_TERMINAL_THEME if State.theme == "dark" else LIGHT_TERMINAL_THEME

    html = traceback_console.export_html(theme=theme, code_format=TRACEBACK_CODE_FORMAT, inline_styles=True)
    with suppress(Exception):
        popup(title=toast_msg, content=put_html(html), size=PopupSize.LARGE)
        run_js(
            "console.error(traceback_msg)",
            traceback_msg="Internal Server Error\n" + traceback_msg,
        )


# 将 WebUI 异常统一交给富文本弹窗处理。
pywebio.session.base.Session.on_task_exception = on_task_exception


class WebUITestError(Exception):
    pass


WEBUI_TEST_ERROR_MESSAGE = "quq"


def raise_exception(x: int = 3) -> NoReturn:
    """用于手动测试 WebUI 异常展示。"""
    if x > 0:
        raise_exception(x - 1)
    else:
        raise WebUITestError(WEBUI_TEST_ERROR_MESSAGE)


def get_alas_config_listen_path(args: DeepValue) -> Iterator[list[str]]:
    for path, d in deep_iter(args, depth=3):
        if isinstance(d, Mapping) and d.get("display") in ["readonly", "hide"]:
            continue
        yield path
