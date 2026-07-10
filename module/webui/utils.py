import datetime
import operator
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable, Generator
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pywebio
from pywebio.exceptions import SessionException
from pywebio.input import PASSWORD
from pywebio.input import input as pywebio_input
from pywebio.output import PopupSize, popup, put_html, toast
from pywebio.session import eval_js, register_thread, run_js
from rich.console import Console
from rich.terminal_theme import TerminalTheme

from module.config.deep import deep_iter
from module.logger import logger
from module.webui.setting import State

if TYPE_CHECKING:
    from queue import Queue

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
    def __init__(self, q: Queue) -> None:
        self.queue = q

    def write(self, s: str):
        self.queue.put(s)


class Task:
    def __init__(self, g: Generator, delay: float, next_run: float | None = None, name: str | None = None) -> None:
        self.g = g
        g.send(None)
        self.delay = delay
        self.next_run = next_run if next_run is not None else time.time()
        self.name = name if name is not None else getattr(self.g, "__name__", type(self.g).__name__)

    def __str__(self) -> str:
        return f"<{self.name} (delay={self.delay})>"

    def __next__(self) -> None:
        return next(self.g)

    def send(self, obj) -> None:
        return self.g.send(obj)

    __repr__ = __str__


class TaskHandler:
    def __init__(self) -> None:
        # List of background running task
        self.tasks: list[Task] = []
        # List of task name to be removed
        self.pending_remove_tasks: list[Task] = []
        # Running task
        self._task = None
        # Task running thread
        self._thread: threading.Thread | None = None
        self._alive = False
        self._lock = threading.Lock()

    def add(self, func, delay: float, *, pending_delete: bool = False) -> None:
        """
        Add a task running background.
        Another way of `self.add_task()`.
        func: Callable or Generator
        """
        if isinstance(func, Callable):
            g = get_generator(func)
        elif isinstance(func, Generator):
            g = func
        self.add_task(Task(g, delay), pending_delete=pending_delete)

    def add_task(self, task: Task, *, pending_delete: bool = False) -> None:
        """
        Add a task running background.
        """
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
        """
        Remove a task in `self.tasks`.

        Args:
            task:
            nowait: if True, remove it right now,
                    otherwise remove when call `self.remove_pending_task`
        """
        if nowait:
            with self._lock:
                self._remove_task(task)
        else:
            self.pending_remove_tasks.append(task)

    def remove_pending_task(self) -> None:
        """
        Remove all pending remove tasks.
        """
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

    def get_task(self, name) -> Task | None:
        with self._lock:
            for task in self.tasks:
                if task.name == name:
                    return task
            return None

    def loop(self) -> None:
        """
        启动后台任务循环。

        这个方法应该在独立线程里运行。
        """
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
        """
        Start task handler.
        """
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


class Switch:
    def __init__(self, status, get_state, name=None):
        """
        Args:
            status
                (dict):A dict describes each state.
                    {
                        0: {
                            'func': (Callable)
                        },
                        1: {
                            'func'
                            'args': (Optional, tuple)
                            'kwargs': (Optional, dict)
                        },
                        2: [
                            func1,
                            {
                                'func': func2
                                'args': args2
                            }
                        ]
                        -1: []
                    }
                (Callable):current state will pass into this function
                    lambda state: do_update(state=state)
            get_state:
                (Callable):
                    return current state
                (Generator):
                    yield current state, do nothing when state not in status
            name:
        """
        self._lock = threading.Lock()
        self.name = name
        self.status = status
        self.get_state = get_state
        if isinstance(get_state, Generator):
            self._generator = get_state
        elif isinstance(get_state, Callable):
            self._generator = self._get_state()

    @staticmethod
    def get_state():
        pass

    def _get_state(self):
        """
        Predefined generator when `get_state` is an callable
        Customize it if you have multiple criteria on state
        """
        _status = self.get_state()
        yield _status
        while True:
            status = self.get_state()
            if _status != status:
                _status = status
                yield _status
                continue
            yield -1

    def switch(self):
        with self._lock:
            r = next(self._generator)
        if callable(self.status):
            self.status(r)
        elif r in self.status:
            f = self.status[r]
            if isinstance(f, (dict, Callable)):
                f = [f]
            for raw_task in f:
                task = {"func": raw_task} if isinstance(raw_task, Callable) else raw_task
                func = task["func"]
                args = task.get("args", ())
                kwargs = task.get("kwargs", {})
                func(*args, **kwargs)

    def g(self) -> Generator:
        g = get_generator(self.switch)
        name = self.name or getattr(self.get_state, "__name__", type(self.get_state).__name__)
        g.__name__ = f"Switch_{name}_refresh"
        return g


def get_generator(func: Callable):
    def _g():
        yield
        while True:
            yield func()

    g = _g()
    g.__name__ = getattr(func, "__name__", type(func).__name__)
    return g


def filepath_css(filename):
    return f"./assets/gui/css/{filename}.css"


def filepath_icon(filename):
    return f"./assets/gui/icon/{filename}.svg"


def add_css(filepath):
    with Path(filepath).open(encoding="utf-8") as f:
        css = f.read().replace("\n", "")
        run_js(f"""$('head').append('<style>{css}</style>')""")


def _read(path):
    with Path(path).open(encoding="utf-8") as f:
        return f.read()


class Icon:
    """
    Storage html of icon.
    """

    ALAS = _read(filepath_icon("alas"))
    SETTING = _read(filepath_icon("setting"))
    RUN = _read(filepath_icon("run"))
    DEVELOP = _read(filepath_icon("develop"))
    ADD = _read(filepath_icon("add"))


str2type = {
    "str": str,
    "float": float,
    "int": int,
    "bool": bool,
    "ignore": lambda x: x,
}


def parse_pin_value(val, valuetype: str | None = None):
    """
    input、textarea 返回 str。
    select 返回选项值（str 或 int）。
    checkbox 返回 [] 或 [True]（由 put_checkbox_ 定义）。
    """
    if isinstance(val, list):
        return bool(val)
    if valuetype:
        return str2type[valuetype](val)
    if isinstance(val, (int, float)):
        return val
    try:
        v = float(val)
    except ValueError:
        return val
    if v.is_integer():
        return int(v)
    return v


def to_pin_value(val):
    """
    Convert bool to checkbox
    """
    if val is True:
        return [True]
    if val is False:
        return []
    return val


def login(password):
    if get_localstorage("password") == str(password):
        return True
    pwd = pywebio_input(label="Please login below.", type=PASSWORD, placeholder="PASSWORD")
    if str(pwd) == str(password):
        set_localstorage("password", str(pwd))
        return True
    toast("Wrong password!", color="error")
    return False


def get_window_visibility_state():
    ret = eval_js("document.visibilityState")
    return ret != "hidden"


# https://pywebio.readthedocs.io/zh_CN/latest/cookbook.html#cookie-and-localstorage-manipulation
def set_localstorage(key, value):
    return run_js("localStorage.setItem(key, value)", key=key, value=value)


def get_localstorage(key):
    return eval_js("localStorage.getItem(key)", key=key)


def re_fullmatch(pattern, string):
    if pattern == "datetime":
        try:
            datetime.datetime.fromisoformat(string)
        except ValueError:
            return False
        else:
            return True
    # elif:
    return re.fullmatch(pattern=pattern, string=string)


def get_next_time(t: datetime.time):
    now = datetime.datetime.now(tz=datetime.UTC).astimezone().time()
    second = (t.hour - now.hour) * 3600 + (t.minute - now.minute) * 60 + (t.second - now.second)
    if second < 0:
        second += 86400
    return second


def on_task_exception(self):
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


# 猴子补丁。
pywebio.session.base.Session.on_task_exception = on_task_exception


class WebUITestError(Exception):
    pass


WEBUI_TEST_ERROR_MESSAGE = "quq"


def raise_exception(x=3):
    """用于手动测试 WebUI 异常展示。"""
    if x > 0:
        raise_exception(x - 1)
    else:
        raise WebUITestError(WEBUI_TEST_ERROR_MESSAGE)


def get_alas_config_listen_path(args):
    for path, d in deep_iter(args, depth=3):
        if d.get("display") in ["readonly", "hide"]:
            continue
        yield path
