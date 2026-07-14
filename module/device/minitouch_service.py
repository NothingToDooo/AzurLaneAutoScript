import socket
import threading
import time
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Protocol

import numpy as np
from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.base.failure import raise_cleanup_errors
from module.base.runtime_random import runtime_random
from module.base.timer import Timer
from module.base.utils import random_rectangle_point
from module.device.method.utils import RETRY_TRIES, handle_adb_error, handle_unknown_host_service, retry_sleep
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from adbutils import AdbConnection
    from numpy.typing import NDArray

    from module.base.type_alias import Area, Point
    from module.device.contracts import MinitouchConfig, MinitouchSession

type Recovery = Callable[[], None]
type SwipePoint = tuple[int, int]


class _CommandTarget(Protocol):
    max_x: int
    max_y: int

    @property
    def orientation(self) -> int: ...

    def minitouch_send(self, builder: CommandBuilder) -> str | None: ...


class _MinitouchRecoveryTarget(Protocol):
    session: MinitouchSession

    def _reset_minitouch_connection(self, *, remove_forward: bool = True) -> None: ...

    def _restart_minitouch_service(self) -> None: ...


def random_normal_distribution(a: float, b: float, n: int = 5) -> float:
    return float(np.mean(runtime_random.uniform(a, b, size=n)))


def random_theta() -> NDArray[np.float64]:
    theta = runtime_random.uniform(0, 2 * np.pi)
    return np.array([np.sin(theta), np.cos(theta)])


def random_rho(dis: float) -> float:
    return random_normal_distribution(-dis, dis)


def insert_swipe(p0: Point, p3: Point, speed: float = 15, min_distance: float = 10) -> list[SwipePoint]:
    """在 p0 与 p3 间生成三阶贝塞尔路径点。

    speed 单位为像素/10ms，相邻输出点至少相距 min_distance 像素。
    """
    p0 = np.array(p0)
    p3 = np.array(p3)

    # 在贝塞尔曲线上随机控制点。
    distance = np.linalg.norm(p3 - p0)
    p1 = 2 / 3 * p0 + 1 / 3 * p3 + random_theta() * random_rho(distance * 0.1)
    p2 = 1 / 3 * p0 + 2 / 3 * p3 + random_theta() * random_rho(distance * 0.1)

    # 在贝塞尔曲线上随机采样 t，中段稀疏，起终点密集。
    segments = max(int(distance / speed) + 1, 5)
    lower = random_normal_distribution(-85, -60)
    upper = random_normal_distribution(80, 90)
    theta = np.arange(lower + 0.0, upper + 0.0001, (upper - lower) / segments)
    ts = np.sin(theta / 180 * np.pi)
    ts = np.sign(ts) * abs(ts) ** 0.9
    ts = (ts - min(ts)) / (max(ts) - min(ts))

    points = []
    prev = (-100, -100)
    for t in ts:
        point = p0 * (1 - t) ** 3 + 3 * p1 * t * (1 - t) ** 2 + 3 * p2 * t**2 * (1 - t) + p3 * t**3
        point = point.astype(int).tolist()
        if np.linalg.norm(np.subtract(point, prev)) < min_distance:
            continue

        points.append(point)
        prev = point

    if len(points[1:]):
        distance = np.linalg.norm(np.subtract(points[1:], points[0]), axis=1)
        mask = np.append(True, distance > min_distance)
        points = np.array(points)[mask].tolist()
        if len(points) <= 1:
            points = [p0, p3]
    else:
        points = [p0, p3]

    return [(int(point[0]), int(point[1])) for point in points]


@dataclass(slots=True)
class Command:
    """
    参考 https://github.com/openstf/minitouch#writable-to-the-socket。
    """

    operation: str
    contact: int = 0
    position: tuple[int, int] = (0, 0)
    ms: int = 10
    pressure: int = 100

    def to_minitouch(self) -> str:
        """
        写入 minitouch socket 的协议字符串。
        """
        if self.operation in {"c", "r"}:
            return f"{self.operation}\n"
        if self.operation in {"d", "m"}:
            x, y = self.position
            return f"{self.operation} {self.contact} {x} {y} {self.pressure}\n"
        if self.operation == "u":
            return f"{self.operation} {self.contact}\n"
        if self.operation == "w":
            return f"{self.operation} {self.ms}\n"
        return ""


class CommandBuilder:
    """按 minitouch socket 协议组合动作命令。"""

    DEFAULT_DELAY = 0.05
    max_x = 1280
    max_y = 720

    def __init__(
        self,
        controller: _CommandTarget,
        contact: int = 0,
        *,
        handle_orientation: bool = True,
    ) -> None:
        self.controller = controller
        self.commands: list[Command] = []
        self.delay = 0
        self.contact = contact
        self.handle_orientation = handle_orientation

    @property
    def orientation(self) -> int:
        if self.handle_orientation:
            return self.controller.orientation
        return 0

    def convert(self, x: int, y: int) -> SwipePoint:
        max_x, max_y = self.controller.max_x, self.controller.max_y
        orientation = self.orientation

        if orientation == 0:
            pass
        elif orientation == 1:
            x, y = 720 - y, x
            max_x, max_y = max_y, max_x
        elif orientation == 2:
            x, y = 1280 - x, 720 - y
        elif orientation == 3:
            x, y = y, 1280 - x
            max_x, max_y = max_y, max_x
        else:
            message = f"Invalid device orientation: {orientation}"
            raise ScriptError(message)

        self.max_x, self.max_y = max_x, max_y
        # minitouch 的最大坐标可能和显示分辨率不同，需要按真实范围缩放。
        x, y = int(x / 1280 * max_x), int(y / 720 * max_y)
        return x, y

    def commit(self) -> CommandBuilder:
        r"""添加 minitouch 命令：'c\n'。"""
        self.commands.append(Command("c"))
        return self

    def reset(self) -> CommandBuilder:
        r"""添加 minitouch 命令：'r\n'。"""
        self.commands.append(Command("r"))
        return self

    def wait(self, ms: int = 10) -> CommandBuilder:
        r"""添加 minitouch 命令：'w <ms>\n'。"""
        self.commands.append(Command("w", ms=ms))
        self.delay += ms
        return self

    def up(self) -> CommandBuilder:
        r"""添加 minitouch 命令：'u <contact>\n'。"""
        self.commands.append(Command("u", contact=self.contact))
        return self

    def down(self, x: int, y: int, pressure: int = 100) -> CommandBuilder:
        r"""添加 minitouch 命令：'d <contact> <x> <y> <pressure>\n'。"""
        x, y = self.convert(x, y)
        self.commands.append(Command("d", contact=self.contact, position=(x, y), pressure=pressure))
        return self

    def move(self, x: int, y: int, pressure: int = 100) -> CommandBuilder:
        r"""添加 minitouch 命令：'m <contact> <x> <y> <pressure>\n'。"""
        x, y = self.convert(x, y)
        self.commands.append(Command("m", contact=self.contact, position=(x, y), pressure=pressure))
        return self

    def clear(self) -> CommandBuilder:
        self.commands = []
        self.delay = 0
        return self

    def to_minitouch(self) -> str:
        out = "".join([command.to_minitouch() for command in self.commands])
        self._check_empty(out)
        return out

    def send(self) -> str | None:
        return self.controller.minitouch_send(builder=self)

    def _check_empty(self, text: str | None = None) -> bool:
        """只有 commit、wait 或 sync 的列表视为空命令。"""
        empty = True
        for command in self.commands:
            if command.operation not in ["c", "w", "s"]:
                empty = False
                break
        if empty:
            logger.warning(f"Command list empty, sending it may cause unexpected behaviour: {text}")
        return empty


class MinitouchNotInstalledError(Exception):
    pass


class MinitouchOccupiedError(Exception):
    pass


MINITOUCH_OCCUPIED_MESSAGE = (
    "Timeout when connecting to minitouch, probably because another connection has been established"
)
MINITOUCH_EMPTY_DATA_MESSAGE = "Received empty data from minitouch, probably because minitouch is not installed"


def _reset_minitouch_after_adb_reconnect(self: _MinitouchRecoveryTarget) -> None:
    self.session.adb_reconnect()
    self._reset_minitouch_connection()


def _restart_adb_server_and_reset_minitouch(self: _MinitouchRecoveryTarget) -> None:
    self.session.adb_start_server()
    self.session.adb_reconnect()
    self._reset_minitouch_connection()


def _restart_minitouch_service_and_reset(self: _MinitouchRecoveryTarget) -> None:
    self._restart_minitouch_service()
    self._reset_minitouch_connection()


def _reset_minitouch_without_forward(self: _MinitouchRecoveryTarget) -> None:
    self._reset_minitouch_connection(remove_forward=False)


def _minitouch_adb_error_recovery(self: _MinitouchRecoveryTarget, error: AdbError) -> Recovery | None:
    if handle_adb_error(error):
        return lambda: _reset_minitouch_after_adb_reconnect(self)
    if handle_unknown_host_service(error):
        return lambda: _restart_adb_server_and_reset_minitouch(self)
    return None


def _minitouch_error_recovery(
    self: _MinitouchRecoveryTarget,
    error: AdbError | MinitouchNotInstalledError | MinitouchOccupiedError | OSError,
) -> Recovery | None:
    if isinstance(error, (ConnectionResetError, ConnectionAbortedError)):
        logger.error(error)
        return lambda: _reset_minitouch_after_adb_reconnect(self)
    if isinstance(error, MinitouchNotInstalledError):
        logger.critical(error)
        raise RequestHumanTakeover from error
    if isinstance(error, MinitouchOccupiedError):
        logger.error(error)
        return lambda: _restart_minitouch_service_and_reset(self)
    if isinstance(error, AdbError):
        return _minitouch_adb_error_recovery(self, error)
    if isinstance(error, BrokenPipeError):
        logger.error(error)
        return lambda: _reset_minitouch_without_forward(self)
    if isinstance(error, OSError):
        logger.error(error)
        return self._reset_minitouch_connection
    return None


def retry[TargetT: _MinitouchRecoveryTarget, **P, ResultT](
    func: Callable[[TargetT, *P.args], ResultT],
) -> Callable[[TargetT, *P.args], ResultT]:
    @wraps(func)
    def retry_wrapper(self: TargetT, *args: P.args, **kwargs: P.kwargs) -> ResultT:
        recovery: Recovery | None = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(recovery):
                    time.sleep(retry_sleep(_))
                    recovery()
                return func(self, *args, **kwargs)
            except RequestHumanTakeover:
                break
            except (AdbError, MinitouchNotInstalledError, MinitouchOccupiedError, OSError) as e:
                recovery = _minitouch_error_recovery(self, e)
                if recovery is None:
                    break

        func_name = getattr(func, "__name__", type(func).__name__)
        logger.critical(f"Retry {func_name}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


class MinitouchController:
    """持有 minitouch 连接、转发、线程与命令构建器。"""

    def __init__(self, session: MinitouchSession) -> None:
        self.session = session
        self._minitouch_port = 0
        self._minitouch_client: socket.socket | None = None
        self._minitouch_pid = ""
        self._minitouch_stream: AdbConnection | None = None
        self.max_x = 1280
        self.max_y = 720
        self._minitouch_init_thread: threading.Thread | None = None
        self._minitouch_lifecycle_lock = threading.RLock()
        self._minitouch_thread_lock = threading.RLock()
        self._minitouch_releasing = False

    @property
    def config(self) -> MinitouchConfig:
        return self.session.config

    @property
    def orientation(self) -> int:
        return self.session.orientation

    def release(self) -> None:
        """在旧 serial 仍有效时按依赖顺序释放控制资源。"""
        errors: list[BaseException] = []
        current_thread = threading.current_thread()
        with self._minitouch_thread_lock:
            self._minitouch_releasing = True
            init_thread = self._minitouch_init_thread
        if init_thread is not None and init_thread is not current_thread:
            try:
                init_thread.join()
            except BaseException as error:  # noqa: BLE001 - join 失败后仍须释放 socket 与端口转发。
                errors.append(error)
        try:
            with self._minitouch_lifecycle_lock:
                with self._minitouch_thread_lock:
                    if self._minitouch_init_thread is init_thread or init_thread is current_thread:
                        self._minitouch_init_thread = None
                try:
                    self._close_minitouch_client()
                except BaseException as error:  # noqa: BLE001 - client 失败后仍须释放转发与 stream。
                    errors.append(error)
                if self._minitouch_port:
                    try:
                        self.session.adb_forward_remove(f"tcp:{self._minitouch_port}")
                    except BaseException as error:  # noqa: BLE001 - 转发失败后仍须清空本地状态。
                        errors.append(error)
                    finally:
                        self._minitouch_port = 0
                try:
                    self._close_minitouch_stream()
                except BaseException as error:  # noqa: BLE001 - stream 失败后仍须失效其余本地状态。
                    errors.append(error)
                self._minitouch_pid = ""
                del_cached_property(self, "_minitouch_builder")
        finally:
            with self._minitouch_thread_lock:
                self._minitouch_releasing = False
        raise_cleanup_errors(errors, message="minitouch resource cleanup failed")

    def release_resource(self) -> None:
        self.release()

    def _close_minitouch_client(self) -> None:
        client = self._minitouch_client
        if client is None:
            return
        try:
            try:
                client.close()
            except OSError as e:
                logger.error(e)
        finally:
            self._minitouch_client = None

    def _close_minitouch_stream(self) -> None:
        stream = self._minitouch_stream
        if stream is None:
            return
        close = getattr(stream, "close", None)
        try:
            if callable(close):
                try:
                    close()
                except OSError as e:
                    logger.error(e)
        finally:
            self._minitouch_stream = None

    def _reset_minitouch_connection(self, *, remove_forward: bool = True) -> None:
        self._close_minitouch_client()
        if remove_forward and self._minitouch_port:
            self.session.adb_forward_remove(f"tcp:{self._minitouch_port}")
            self._minitouch_port = 0
        self._minitouch_pid = ""
        del_cached_property(self, "_minitouch_builder")

    def _ensure_minitouch_executable(self) -> None:
        path = self.config.MINITOUCH_FILEPATH_REMOTE
        self.session.adb_shell(["chmod", "755", path])
        state = self.session.adb_shell(f"if [ -x {path} ]; then echo ok; else echo missing; fi").strip()
        if state == "ok":
            return
        message = f"未找到可执行的 minitouch：{path}。请先把 MuMu 当前 ABI 对应的 minitouch 推送到这个路径。"
        raise MinitouchNotInstalledError(message)

    def _start_minitouch_service(self) -> None:
        if self._minitouch_stream is not None:
            return
        path = self.config.MINITOUCH_FILEPATH_REMOTE
        self._ensure_minitouch_executable()
        logger.info(f"Start minitouch: {path}")
        self._minitouch_stream = self.session.adb_shell([path], stream=True, recvall=False)

    def _find_minitouch_pids(self) -> set[str]:
        pids = {self._minitouch_pid} if self._minitouch_pid else set()
        output = self.session.adb_shell("(ps -A; ps) 2>/dev/null | grep '[m]initouch'", timeout=5)
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(parts[1])
        return pids

    def _restart_minitouch_service(self) -> None:
        logger.info("Restart minitouch")
        self._close_minitouch_client()
        self._close_minitouch_stream()
        for pid in self._find_minitouch_pids():
            logger.info(f"Kill minitouch pid: {pid}")
            self.session.adb_shell(["kill", pid])
        self._minitouch_pid = ""
        self._start_minitouch_service()

    @cached_property
    @retry
    def _minitouch_builder(self) -> CommandBuilder:
        self.minitouch_init()
        return CommandBuilder(self)

    @property
    def minitouch_builder(self) -> CommandBuilder:
        current_thread = threading.current_thread()
        with self._minitouch_thread_lock:
            init_thread = self._minitouch_init_thread
        if init_thread is not None and init_thread is not current_thread:
            init_thread.join()
        with self._minitouch_lifecycle_lock:
            with self._minitouch_thread_lock:
                if self._minitouch_init_thread is init_thread:
                    self._minitouch_init_thread = None
                if self._minitouch_releasing:
                    message = "minitouch is being released"
                    raise RuntimeError(message)
            return self._minitouch_builder

    def early_minitouch_init(self) -> None:
        """截图阶段异步预热 minitouch，使首次点击快约 0.05 秒。"""
        with self._minitouch_thread_lock:
            if (
                self._minitouch_releasing
                or has_cached_property(self, "_minitouch_builder")
                or self._minitouch_init_thread is not None
            ):
                return

            def early_minitouch_init_func() -> None:
                current_thread = threading.current_thread()
                try:
                    # 覆盖 cached_property 写入；release 要么先阻止启动，要么等完整发布后再清理。
                    with self._minitouch_lifecycle_lock:
                        with self._minitouch_thread_lock:
                            if self._minitouch_releasing:
                                return
                        _ = self._minitouch_builder
                finally:
                    with self._minitouch_thread_lock:
                        if self._minitouch_init_thread is current_thread:
                            self._minitouch_init_thread = None

            thread = threading.Thread(target=early_minitouch_init_func, daemon=True)
            self._minitouch_init_thread = thread
            try:
                # pointer 发布与 start 在同一个临界区，release 永远看不到未启动线程。
                thread.start()
            except BaseException:
                self._minitouch_init_thread = None
                raise

    def early_init(self) -> None:
        self.early_minitouch_init()

    def minitouch_init(self) -> None:
        logger.hr("MiniTouch init")
        max_x, max_y = 1280, 720
        max_contacts = 2
        max_pressure = 50

        self._close_minitouch_client()

        self.session.get_orientation()

        self._start_minitouch_service()
        self._minitouch_port = self.session.adb_forward("localabstract:minitouch")

        retry_timeout = Timer(2).start()
        while 1:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(1)
            client.connect(("127.0.0.1", self._minitouch_port))
            self._minitouch_client = client

            socket_out = client.makefile()

            # v <version>
            # 协议版本，通常是 1，这里不用。
            try:
                out = socket_out.readline().replace("\n", "").replace("\r", "")
            except TimeoutError as e:
                client.close()
                raise MinitouchOccupiedError(MINITOUCH_OCCUPIED_MESSAGE) from e
            logger.info(out)

            # ^ <max-contacts> <max-x> <max-y> <max-pressure>
            out = socket_out.readline().replace("\n", "").replace("\r", "")
            logger.info(out)
            try:
                _, max_contacts, max_x, max_y, max_pressure, *_ = out.split(" ")
                break
            except ValueError as e:
                client.close()
                if retry_timeout.reached():
                    raise MinitouchNotInstalledError(MINITOUCH_EMPTY_DATA_MESSAGE) from e
                # minitouch 可能还没启动完成。
                self.session.sleep(1)
                continue

        self.max_x = int(max_x)
        self.max_y = int(max_y)

        # $ <pid>
        out = socket_out.readline().replace("\n", "").replace("\r", "")
        logger.info(out)
        _, pid = out.split(" ")
        self._minitouch_pid = pid

        logger.info(f"minitouch running on port: {self._minitouch_port}, pid: {self._minitouch_pid}")
        logger.info(f"max_contact: {max_contacts}; max_x: {max_x}; max_y: {max_y}; max_pressure: {max_pressure}")

    def minitouch_send(self, builder: CommandBuilder) -> None:
        content = builder.to_minitouch()
        byte_content = content.encode("utf-8")
        client = self._minitouch_client
        if client is None:
            logger.critical("minitouch socket is not connected")
            raise RequestHumanTakeover
        client.sendall(byte_content)
        client.recv(0)
        time.sleep(builder.delay / 1000 + builder.DEFAULT_DELAY)
        builder.clear()

    @retry
    def click_minitouch(self, x: int, y: int) -> None:
        builder = self.minitouch_builder
        builder.down(x, y).commit()
        builder.up().commit()
        builder.send()

    def click(self, x: int, y: int) -> None:
        return self.click_minitouch(x, y)

    @retry
    def long_click_minitouch(self, x: int, y: int, duration: float = 1.0) -> None:
        duration = int(duration * 1000)
        builder = self.minitouch_builder
        builder.down(x, y).commit().wait(duration)
        builder.up().commit()
        builder.send()

    def long_click(self, x: int, y: int, duration: float = 1.0) -> None:
        return self.long_click_minitouch(x, y, duration)

    @retry
    def swipe_minitouch(self, p1: Point, p2: Point) -> None:
        points = insert_swipe(p0=p1, p3=p2)
        builder = self.minitouch_builder

        builder.down(*points[0]).commit().wait(10)
        builder.send()

        for point in points[1:]:
            builder.move(*point).commit().wait(10)
        builder.send()

        builder.up().commit()
        builder.send()

    def swipe(self, p1: Point, p2: Point) -> None:
        return self.swipe_minitouch(p1, p2)

    @retry
    def drag_minitouch(self, p1: Point, p2: Point, point_random: Area = (-10, -10, 10, 10)) -> None:
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        points = insert_swipe(p0=p1, p3=p2, speed=20)
        builder = self.minitouch_builder

        builder.down(*points[0]).commit().wait(10)
        builder.send()

        for point in points[1:]:
            builder.move(*point).commit().wait(10)
        builder.send()

        builder.move(*p2).commit().wait(140)
        builder.move(*p2).commit().wait(140)
        builder.send()

        builder.up().commit()
        builder.send()

    def drag(self, p1: Point, p2: Point, point_random: Area = (-10, -10, 10, 10)) -> None:
        return self.drag_minitouch(p1, p2, point_random=point_random)
