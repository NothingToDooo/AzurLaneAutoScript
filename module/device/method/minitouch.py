import socket
import threading
import time
from functools import wraps

import numpy as np
from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.base.runtime_random import runtime_random
from module.base.timer import Timer
from module.base.utils import random_rectangle_point
from module.device.connection import Connection
from module.device.method.utils import RETRY_TRIES, handle_adb_error, handle_unknown_host_service, retry_sleep
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger


def random_normal_distribution(a, b, n=5):
    return np.mean(runtime_random.uniform(a, b, size=n))


def random_theta():
    theta = runtime_random.uniform(0, 2 * np.pi)
    return np.array([np.sin(theta), np.cos(theta)])


def random_rho(dis):
    return random_normal_distribution(-dis, dis)


def insert_swipe(p0, p3, speed=15, min_distance=10):
    """
    在起点和终点之间插入路径点。

    先生成一条三阶贝塞尔曲线。

    参数：
        p0：起点。
        p3：终点。
        speed：平均移动速度，单位为每 10ms 的像素数。
        min_distance:

    返回：
        list[list[int]]：路径点列表。

    示例：
        > insert_swipe((400, 400), (600, 600), speed=20)
        [[400, 400], [406, 406], [416, 415], [429, 428], [444, 442], [462, 459], [481, 478], [504, 500], [527, 522],
        [545, 540], [560, 557], [573, 570], [584, 582], [592, 590], [597, 596], [600, 600]]
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

    # 生成三阶贝塞尔曲线。
    points = []
    prev = (-100, -100)
    for t in ts:
        point = p0 * (1 - t) ** 3 + 3 * p1 * t * (1 - t) ** 2 + 3 * p2 * t**2 * (1 - t) + p3 * t**3
        point = point.astype(int).tolist()
        if np.linalg.norm(np.subtract(point, prev)) < min_distance:
            continue

        points.append(point)
        prev = point

    # 删除过近的路径点。
    if len(points[1:]):
        distance = np.linalg.norm(np.subtract(points[1:], points[0]), axis=1)
        mask = np.append(True, distance > min_distance)
        points = np.array(points)[mask].tolist()
        if len(points) <= 1:
            points = [p0, p3]
    else:
        points = [p0, p3]

    return points


class Command:
    def __init__(
        self,
        operation: str,
        contact: int = 0,
        x: int = 0,
        y: int = 0,
        ms: int = 10,
        pressure: int = 100,
    ):
        """
        参考 https://github.com/openstf/minitouch#writable-to-the-socket。

        参数：
            operation: c, r, d, m, u, w
            contact:
            x:
            y:
            ms:
            pressure:
        """
        self.operation = operation
        self.contact = contact
        self.x = x
        self.y = y
        self.ms = ms
        self.pressure = pressure

    def to_minitouch(self) -> str:
        """
        String that write into minitouch socket
        """
        if self.operation == "c" or self.operation == "r":
            return f"{self.operation}\n"
        if self.operation == "d" or self.operation == "m":
            return f"{self.operation} {self.contact} {self.x} {self.y} {self.pressure}\n"
        if self.operation == "u":
            return f"{self.operation} {self.contact}\n"
        if self.operation == "w":
            return f"{self.operation} {self.ms}\n"
        return ""


class CommandBuilder:
    """构建 minitouch 命令字符串。

    可用它按需构造自定义动作：

        with safe_connection(_DEVICE_ID) as connection:
            builder = CommandBuilder()
            builder.down(0, 400, 400, 50)
            builder.commit()
            builder.move(0, 500, 500, 50)
            builder.commit()
            builder.move(0, 800, 400, 50)
            builder.commit()
            builder.up(0)
            builder.commit()
            builder.publish(connection)

    """

    DEFAULT_DELAY = 0.05
    max_x = 1280
    max_y = 720

    def __init__(
        self,
        device,
        contact=0,
        handle_orientation=True,
    ):
        """
        参数：
            device:
        """
        self.device = device
        self.commands = []
        self.delay = 0
        self.contact = contact
        self.handle_orientation = handle_orientation

    @property
    def orientation(self):
        if self.handle_orientation:
            return self.device.orientation
        return 0

    def convert(self, x, y):
        max_x, max_y = self.device.max_x, self.device.max_y
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
            raise ScriptError(f"Invalid device orientation: {orientation}")

        self.max_x, self.max_y = max_x, max_y
        # minitouch 的最大坐标可能和显示分辨率不同，需要按真实范围缩放。
        x, y = int(x / 1280 * max_x), int(y / 720 * max_y)
        return x, y

    def commit(self):
        """添加 minitouch 命令：'c\n'。"""
        self.commands.append(Command("c"))
        return self

    def reset(self):
        """添加 minitouch 命令：'r\n'。"""
        self.commands.append(Command("r"))
        return self

    def wait(self, ms=10):
        """添加 minitouch 命令：'w <ms>\n'。"""
        self.commands.append(Command("w", ms=ms))
        self.delay += ms
        return self

    def up(self):
        """添加 minitouch 命令：'u <contact>\n'。"""
        self.commands.append(Command("u", contact=self.contact))
        return self

    def down(self, x, y, pressure=100):
        """添加 minitouch 命令：'d <contact> <x> <y> <pressure>\n'。"""
        x, y = self.convert(x, y)
        self.commands.append(Command("d", x=x, y=y, contact=self.contact, pressure=pressure))
        return self

    def move(self, x, y, pressure=100):
        """添加 minitouch 命令：'m <contact> <x> <y> <pressure>\n'。"""
        x, y = self.convert(x, y)
        self.commands.append(Command("m", x=x, y=y, contact=self.contact, pressure=pressure))
        return self

    def clear(self):
        """清空当前命令。"""
        self.commands = []
        self.delay = 0
        return self

    def to_minitouch(self) -> str:
        out = "".join([command.to_minitouch() for command in self.commands])
        self._check_empty(out)
        return out

    def send(self):
        return self.device.minitouch_send(builder=self)

    def _check_empty(self, text=None):
        """
        有效命令列表必须包含实际操作，不能只有 commit。

        返回：
            bool：命令是否为空。
        """
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


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        参数：
            self (Minitouch):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 无法自动处理。
            except RequestHumanTakeover:
                break
            # ADB server 被杀掉。
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
                    if self._minitouch_port:
                        self.adb_forward_remove(f"tcp:{self._minitouch_port}")
                    del_cached_property(self, "_minitouch_builder")
            # 模拟器已关闭。
            except ConnectionAbortedError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
                    if self._minitouch_port:
                        self.adb_forward_remove(f"tcp:{self._minitouch_port}")
                    del_cached_property(self, "_minitouch_builder")
            # minitouch 返回空数据，通常是没有安装。
            except MinitouchNotInstalledError as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()
                    if self._minitouch_port:
                        self.adb_forward_remove(f"tcp:{self._minitouch_port}")
                    del_cached_property(self, "_minitouch_builder")
            # 连接 minitouch 超时，通常是已有连接占用。
            except MinitouchOccupiedError as e:
                logger.error(e)

                def init():
                    self.restart_uiautomator2()
                    if self._minitouch_port:
                        self.adb_forward_remove(f"tcp:{self._minitouch_port}")
                    del_cached_property(self, "_minitouch_builder")
            # ADB 错误。
            except AdbError as e:
                if handle_adb_error(e):

                    def init():
                        self.adb_reconnect()
                        if self._minitouch_port:
                            self.adb_forward_remove(f"tcp:{self._minitouch_port}")
                        del_cached_property(self, "_minitouch_builder")
                elif handle_unknown_host_service(e):

                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                        if self._minitouch_port:
                            self.adb_forward_remove(f"tcp:{self._minitouch_port}")
                        del_cached_property(self, "_minitouch_builder")
                else:
                    break
            except BrokenPipeError as e:
                logger.error(e)

                def init():
                    del_cached_property(self, "_minitouch_builder")
            # 未知错误，按不可恢复处理。
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        logger.critical(f"Retry {func.__name__}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


class Minitouch(Connection):
    _minitouch_port: int = 0
    _minitouch_client: socket.socket = None
    _minitouch_pid: int
    max_x: int
    max_y: int
    _minitouch_init_thread = None

    @cached_property
    @retry
    def _minitouch_builder(self):
        self.minitouch_init()
        return CommandBuilder(self)

    @property
    def minitouch_builder(self):
        # 等待初始化线程结束。
        if self._minitouch_init_thread is not None:
            self._minitouch_init_thread.join()
            del self._minitouch_init_thread
            self._minitouch_init_thread = None

        return self._minitouch_builder

    def early_minitouch_init(self):
        """
        Alas 开始截图时提前开线程初始化 minitouch 连接。

        这样可以让第一次点击快约 0.05 秒。
        """
        if has_cached_property(self, "_minitouch_builder"):
            return

        def early_minitouch_init_func():
            _ = self._minitouch_builder

        thread = threading.Thread(target=early_minitouch_init_func, daemon=True)
        self._minitouch_init_thread = thread
        thread.start()

    def minitouch_init(self):
        logger.hr("MiniTouch init")
        max_x, max_y = 1280, 720
        max_contacts = 2
        max_pressure = 50

        # 尝试关闭已有连接。
        if self._minitouch_client is not None:
            try:
                self._minitouch_client.close()
            except Exception as e:
                logger.error(e)
            del self._minitouch_client

        self.get_orientation()

        self._minitouch_port = self.adb_forward("localabstract:minitouch")

        # 不需要手动启动，minitouch 已经由 uiautomator2 拉起。
        # self.adb_shell([self.config.MINITOUCH_FILEPATH_REMOTE])

        retry_timeout = Timer(2).start()
        while 1:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(1)
            client.connect(("127.0.0.1", self._minitouch_port))
            self._minitouch_client = client

            # 读取 minitouch server 信息。
            socket_out = client.makefile()

            # v <version>
            # 协议版本，通常是 1，这里不用。
            try:
                out = socket_out.readline().replace("\n", "").replace("\r", "")
            except TimeoutError as e:
                client.close()
                raise MinitouchOccupiedError(
                    "Timeout when connecting to minitouch, probably because another connection has been established"
                ) from e
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
                    raise MinitouchNotInstalledError(
                        "Received empty data from minitouch, probably because minitouch is not installed"
                    ) from e
                # minitouch 可能还没启动完成。
                self.sleep(1)
                continue

        # self.max_contacts = max_contacts
        self.max_x = int(max_x)
        self.max_y = int(max_y)
        # self.max_pressure = max_pressure

        # $ <pid>
        out = socket_out.readline().replace("\n", "").replace("\r", "")
        logger.info(out)
        _, pid = out.split(" ")
        self._minitouch_pid = pid

        logger.info(f"minitouch running on port: {self._minitouch_port}, pid: {self._minitouch_pid}")
        logger.info(f"max_contact: {max_contacts}; max_x: {max_x}; max_y: {max_y}; max_pressure: {max_pressure}")

    def minitouch_send(self, builder: CommandBuilder):
        content = builder.to_minitouch()
        # logger.info("发送操作: {}".format(content.replace("\n", "\\n")))
        byte_content = content.encode("utf-8")
        self._minitouch_client.sendall(byte_content)
        self._minitouch_client.recv(0)
        time.sleep(self.minitouch_builder.delay / 1000 + builder.DEFAULT_DELAY)
        builder.clear()

    @retry
    def click_minitouch(self, x, y):
        builder = self.minitouch_builder
        builder.down(x, y).commit()
        builder.up().commit()
        builder.send()

    @retry
    def long_click_minitouch(self, x, y, duration=1.0):
        duration = int(duration * 1000)
        builder = self.minitouch_builder
        builder.down(x, y).commit().wait(duration)
        builder.up().commit()
        builder.send()

    @retry
    def swipe_minitouch(self, p1, p2):
        points = insert_swipe(p0=p1, p3=p2)
        builder = self.minitouch_builder

        builder.down(*points[0]).commit().wait(10)
        builder.send()

        for point in points[1:]:
            builder.move(*point).commit().wait(10)
        builder.send()

        builder.up().commit()
        builder.send()

    @retry
    def drag_minitouch(self, p1, p2, point_random=(-10, -10, 10, 10)):
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
