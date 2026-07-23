from typing import TYPE_CHECKING, Literal, Protocol, overload

if TYPE_CHECKING:
    from collections.abc import Iterable

    from adbutils import AdbClient, AdbConnection

    from module.base.type_alias import Area, ImageArray, Point
    from module.device.control_options import Duration
    from module.device.minitouch_service import CommandBuilder
    from module.device.mumu_instance import MuMuInstance
    from module.map.map_grids import SelectedGrids

type AdbCommand = str | Iterable[str | int]


class AdbShellSession(Protocol):
    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[False] = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[True] = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> bytes: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[False],
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> AdbConnection: ...


class AppSession(AdbShellSession, Protocol):
    @property
    def package(self) -> str: ...


class AdbRecoverySession(Protocol):
    def adb_start_server(self) -> int: ...

    def adb_reconnect(self) -> None: ...

    def detect_package(self) -> None: ...


class RetrySession(AppSession, AdbRecoverySession, Protocol):
    pass


class MinitouchConfig(Protocol):
    MINITOUCH_FILEPATH_REMOTE: str


class DeviceConfig(MinitouchConfig, Protocol):
    Emulator_Serial: str
    Emulator_MuMuPath: str


class MinitouchSession(AdbShellSession, Protocol):
    @property
    def config(self) -> MinitouchConfig: ...

    @property
    def orientation(self) -> int: ...

    def adb_reconnect(self) -> None: ...

    def adb_start_server(self) -> int: ...

    def adb_forward(self, remote: str) -> int: ...

    def adb_forward_remove(self, local: str) -> None: ...

    def get_orientation(self) -> int: ...

    @staticmethod
    def sleep(second: Duration, /) -> None: ...


class DeviceSession(MinitouchSession, RetrySession, Protocol):
    @property
    def config(self) -> DeviceConfig: ...

    @property
    def serial(self) -> str: ...

    @property
    def is_mumu_family(self) -> bool: ...

    @property
    def is_mumu12_family(self) -> bool: ...

    @property
    def adb_client(self) -> AdbClient: ...

    def adb_getprop(self, name: str) -> str: ...

    def list_device(self) -> SelectedGrids: ...

    def list_known_packages(self, *, show_log: bool = True) -> list[str]: ...

    def bind_serial(self, serial: str) -> bool: ...


class CaptureRuntime(Protocol):
    @property
    def emulator_instance(self) -> MuMuInstance: ...


class CaptureService(Protocol):
    @property
    def mumu_runtime(self) -> CaptureRuntime: ...

    def screenshot(self) -> ImageArray: ...

    def release(self) -> None: ...


class ControllerService(Protocol):
    @property
    def session(self) -> MinitouchSession: ...

    @property
    def minitouch_builder(self) -> CommandBuilder: ...

    def release(self) -> None: ...

    def click(self, x: int, y: int) -> None: ...

    def long_click(self, x: int, y: int, duration: float = 1.0) -> None: ...

    def swipe(self, p1: Point, p2: Point) -> None: ...

    def drag(self, p1: Point, p2: Point, point_random: Area = (-10, -10, 10, 10)) -> None: ...


class AppControllerService(Protocol):
    @property
    def session(self) -> AppSession: ...

    def current(self) -> str: ...

    def is_running(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
