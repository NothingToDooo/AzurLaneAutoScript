from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast, overload, override

import numpy as np
import pytest
from adbutils import AdbClient
from adbutils.errors import AdbError

from module.base.decorator import cached_property
from module.config.config import AzurLaneConfig
from module.device import connection as connection_module
from module.device.connection import Connection
from module.device.device import Device
from module.device.minitouch_service import CommandBuilder, MinitouchController
from module.device.mumu_instance import MuMuInstance
from module.device.runtime import DeviceRuntime, MumuRuntime
from module.exception import EmulatorNotRunningError
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Iterable

    from adbutils import AdbConnection

    from module.base.type_alias import Area, ImageArray, Point
    from module.device.control_options import Duration


class _MinitouchConfigDouble:
    MINITOUCH_FILEPATH_REMOTE = "/data/local/tmp/minitouch"
    Emulator_Serial = "127.0.0.1:16384"
    Emulator_MuMuPath = "C:/MuMu/MuMuNxMain.exe"


class _DeviceSessionDouble:
    def __init__(
        self,
        *,
        fail_on_access: bool = False,
        forward_remove_error: Exception | None = None,
    ) -> None:
        self.accesses: list[str] = []
        self._fail_on_access = fail_on_access
        self._forward_remove_error = forward_remove_error
        self._config = _MinitouchConfigDouble()
        self._adb_client = AdbClient()

    def _record(self, name: str) -> None:
        self.accesses.append(name)
        if self._fail_on_access:
            message = f"服务构造期间不应读取 session.{name}"
            raise AssertionError(message)

    @property
    def package(self) -> str:
        self._record("package")
        return "com.bilibili.azurlane"

    @property
    def config(self) -> _MinitouchConfigDouble:
        self._record("config")
        return self._config

    @property
    def orientation(self) -> int:
        self._record("orientation")
        return 0

    @property
    def serial(self) -> str:
        self._record("serial")
        return "127.0.0.1:16384"

    @property
    def is_mumu_family(self) -> bool:
        self._record("is_mumu_family")
        return True

    @property
    def is_mumu12_family(self) -> bool:
        self._record("is_mumu12_family")
        return True

    @property
    def adb_client(self) -> AdbClient:
        self._record("adb_client")
        return self._adb_client

    @overload
    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: Literal[False] = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str: ...

    @overload
    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: Literal[True],
        recvall: Literal[True] = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> bytes: ...

    @overload
    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: Literal[True],
        recvall: Literal[False],
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> AdbConnection: ...

    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: bool = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str | bytes | AdbConnection:
        del cmd, recvall, timeout, rstrip
        self._record("adb_shell")
        if stream:
            message = "streaming adb_shell is not used by this test double"
            raise AssertionError(message)
        return ""

    def adb_start_server(self) -> int:
        self._record("adb_start_server")
        return 0

    def adb_reconnect(self) -> None:
        self._record("adb_reconnect")

    def detect_package(self) -> None:
        self._record("detect_package")

    def adb_forward(self, remote: str) -> int:
        del remote
        self._record("adb_forward")
        return 12345

    def adb_forward_remove(self, local: str) -> None:
        del local
        self._record("adb_forward_remove")
        if self._forward_remove_error is not None:
            raise self._forward_remove_error

    def get_orientation(self) -> int:
        self._record("get_orientation")
        return 0

    @staticmethod
    def sleep(second: Duration) -> None:
        del second

    def adb_getprop(self, name: str) -> str:
        del name
        self._record("adb_getprop")
        return ""

    def list_device(self) -> SelectedGrids:
        self._record("list_device")
        return SelectedGrids([])

    def list_known_packages(self, *, show_log: bool = True) -> list[str]:
        del show_log
        self._record("list_known_packages")
        return []


class _MumuRuntimeDouble:
    def __init__(
        self,
        session: _DeviceSessionDouble,
        calls: list[str] | None = None,
        *,
        invalidate_error: BaseException | None = None,
    ) -> None:
        self.session = session
        self._calls = [] if calls is None else calls
        self._invalidate_error = invalidate_error
        self._emulator_instance = MuMuInstance(
            executable=Path("C:/MuMu/nx_main/MuMuNxMain.exe"),
            instance_id=0,
            name="MuMuPlayer-15.0-0",
            config_dir=Path("C:/MuMu/vms/MuMuPlayer-15.0-0/configs"),
        )
        self._lifecycle_result = True
        self.lifecycle_calls: list[str] = []
        self.health_check_calls: list[str] = []

    @property
    def emulator_instance(self) -> MuMuInstance:
        return self._emulator_instance

    def emulator_start(self) -> bool:
        self.lifecycle_calls.append("start")
        return self._lifecycle_result

    def emulator_stop(self) -> bool:
        self.lifecycle_calls.append("stop")
        return self._lifecycle_result

    def emulator_start_watch(self) -> bool:
        self.lifecycle_calls.append("watch")
        return self._lifecycle_result

    def check_mumu_app_keep_alive(self) -> bool:
        self.health_check_calls.append("app_keep_alive")
        return self._lifecycle_result

    def check_mumu_bridge_network(self) -> bool:
        self.health_check_calls.append("bridge_network")
        return self._lifecycle_result

    def check_after_connected(self) -> None:
        self.health_check_calls.append("after_connected")

    def diagnose_adb_connect_refused(self) -> None:
        self.health_check_calls.append("diagnose_refused")

    def invalidate_serial(self) -> None:
        self._calls.append("mumu")
        if self._invalidate_error is not None:
            raise self._invalidate_error


class _CaptureServiceDouble:
    def __init__(
        self,
        mumu_runtime: _MumuRuntimeDouble,
        calls: list[str] | None = None,
        *,
        release_error: BaseException | None = None,
    ) -> None:
        self.mumu_runtime = mumu_runtime
        self._calls = [] if calls is None else calls
        self._release_error = release_error
        self._image = np.zeros((1, 1, 3), dtype=np.uint8)

    def screenshot(self) -> ImageArray:
        return self._image.copy()

    def release(self) -> None:
        self._calls.append("capture")
        if self._release_error is not None:
            raise self._release_error


class _ControllerServiceDouble:
    max_x = 1280
    max_y = 720
    orientation = 0

    def __init__(
        self,
        session: _DeviceSessionDouble,
        calls: list[str] | None = None,
        *,
        release_error: BaseException | None = None,
    ) -> None:
        self.session = session
        self._calls = [] if calls is None else calls
        self._release_error = release_error
        self._minitouch_builder = CommandBuilder(self, handle_orientation=False)
        self.sent_builders: list[CommandBuilder] = []
        self.clicks: list[tuple[int, int]] = []
        self.long_clicks: list[tuple[int, int, float]] = []
        self.swipes: list[tuple[Point, Point]] = []
        self.drags: list[tuple[Point, Point, Area]] = []

    @property
    def minitouch_builder(self) -> CommandBuilder:
        return self._minitouch_builder

    def minitouch_send(self, builder: CommandBuilder) -> None:
        self.sent_builders.append(builder)

    def release(self) -> None:
        self._calls.append("controller")
        if self._release_error is not None:
            raise self._release_error

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

    def long_click(self, x: int, y: int, duration: float = 1.0) -> None:
        self.long_clicks.append((x, y, duration))

    def swipe(self, p1: Point, p2: Point) -> None:
        self.swipes.append((p1, p2))

    def drag(self, p1: Point, p2: Point, point_random: Area = (-10, -10, 10, 10)) -> None:
        self.drags.append((p1, p2, point_random))


class _AppControllerServiceDouble:
    def __init__(self, session: _DeviceSessionDouble) -> None:
        self.session = session
        self._current_package = ""
        self._running = False
        self.start_calls = 0
        self.stop_calls = 0

    def current(self) -> str:
        return self._current_package

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class _DeviceConfig(AzurLaneConfig):
    def __init__(self) -> None:
        pass

    @property
    @override
    def is_actual_task(self) -> bool:
        return False


def test_runtime_services_share_one_adb_session_without_constructor_io() -> None:
    session = _DeviceSessionDouble(fail_on_access=True)

    runtime = DeviceRuntime.create(session)

    assert runtime.adb_session is session
    assert runtime.mumu_runtime.session is session
    assert runtime.controller.session is session
    assert runtime.app_controller.session is session
    assert runtime.capture.mumu_runtime is runtime.mumu_runtime
    assert session.accesses == []


def test_device_builds_runtime_before_first_connection_and_reuses_it_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[tuple[int, object]] = []
    starts: list[object] = []
    instance = SimpleNamespace(type="unused")

    class _MumuRuntime:
        emulator_instance = instance

        def emulator_start(self) -> bool:
            starts.append(self)
            return True

    runtime = SimpleNamespace(
        adb_session=None,
        mumu_runtime=_MumuRuntime(),
        capture=object(),
        controller=SimpleNamespace(),
        app_controller=object(),
    )

    def create(adb_session: Device) -> SimpleNamespace:
        runtime.adb_session = adb_session
        return runtime

    def connection_init(device: Device, config: _DeviceConfig) -> None:
        attempts.append((id(device.runtime), device.runtime.adb_session))
        device.config = config
        if len(attempts) < 4:
            raise EmulatorNotRunningError

    config = _DeviceConfig()
    monkeypatch.setattr(DeviceRuntime, "create", staticmethod(create))
    monkeypatch.setattr(Connection, "__init__", connection_init)
    monkeypatch.setattr(Device, "screenshot_interval_set", lambda _device: None)

    device = Device(config)

    assert len(attempts) == 4
    assert {runtime_id for runtime_id, _ in attempts} == {id(runtime)}
    assert all(session is device for _, session in attempts)
    assert starts == [runtime.mumu_runtime] * 3


def test_runtime_releases_serial_services_in_explicit_order() -> None:
    calls: list[str] = []
    session = _DeviceSessionDouble()
    mumu_runtime = _MumuRuntimeDouble(session, calls)
    runtime = DeviceRuntime(
        adb_session=session,
        mumu_runtime=cast("MumuRuntime", mumu_runtime),
        capture=_CaptureServiceDouble(mumu_runtime, calls),
        controller=_ControllerServiceDouble(session, calls),
        app_controller=_AppControllerServiceDouble(session),
    )

    runtime.release_serial()
    runtime.release_serial()

    assert calls == ["controller", "capture", "mumu", "controller", "capture", "mumu"]


def test_runtime_finishes_capture_and_mumu_cleanup_after_controller_error() -> None:
    calls: list[str] = []
    session = _DeviceSessionDouble()
    mumu_runtime = _MumuRuntimeDouble(session, calls)
    error = OSError("forward failed")

    runtime = DeviceRuntime(
        adb_session=session,
        mumu_runtime=cast("MumuRuntime", mumu_runtime),
        capture=_CaptureServiceDouble(mumu_runtime, calls),
        controller=_ControllerServiceDouble(session, calls, release_error=error),
        app_controller=_AppControllerServiceDouble(session),
    )

    with pytest.raises(OSError, match="forward failed"):
        runtime.release_serial()

    assert calls == ["controller", "capture", "mumu"]


def test_runtime_preserves_every_serial_cleanup_failure_in_order() -> None:
    class _InvalidationSignal(BaseException):
        pass

    calls: list[str] = []
    session = _DeviceSessionDouble()
    controller_error = OSError("controller cleanup failed")
    capture_error = RuntimeError("capture cleanup failed")
    invalidation_error = _InvalidationSignal("serial invalidation failed")
    mumu_runtime = _MumuRuntimeDouble(session, calls, invalidate_error=invalidation_error)
    runtime = DeviceRuntime(
        adb_session=session,
        mumu_runtime=cast("MumuRuntime", mumu_runtime),
        capture=_CaptureServiceDouble(mumu_runtime, calls, release_error=capture_error),
        controller=_ControllerServiceDouble(session, calls, release_error=controller_error),
        app_controller=_AppControllerServiceDouble(session),
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        runtime.release_serial()

    assert raised.value.exceptions == (controller_error, capture_error, invalidation_error)
    assert calls == ["controller", "capture", "mumu"]


def test_minitouch_release_clears_state_when_forward_removal_fails() -> None:
    closed: list[str] = []
    session = _DeviceSessionDouble(forward_remove_error=OSError("remove failed"))
    controller = MinitouchController(session)
    vars(controller).update(
        _minitouch_port=23456,
        _minitouch_client=SimpleNamespace(close=lambda: closed.append("client")),
        _minitouch_stream=SimpleNamespace(close=lambda: closed.append("stream")),
        _minitouch_pid="4312",
        _minitouch_builder=object(),
    )

    with pytest.raises(OSError, match="remove failed"):
        controller.release()

    assert closed == ["client", "stream"]
    assert vars(controller)["_minitouch_port"] == 0
    assert vars(controller)["_minitouch_client"] is None
    assert vars(controller)["_minitouch_stream"] is None
    assert vars(controller)["_minitouch_pid"] == ""
    assert "_minitouch_builder" not in controller.__dict__
    controller.release()


def test_minitouch_release_preserves_every_failure_and_clears_local_state() -> None:
    class _StreamCloseSignal(BaseException):
        pass

    client_error = RuntimeError("client close failed")
    forward_error = OSError("forward removal failed")
    stream_error = _StreamCloseSignal("stream close interrupted")

    def fail_client_close() -> None:
        raise client_error

    def fail_stream_close() -> None:
        raise stream_error

    session = _DeviceSessionDouble(forward_remove_error=forward_error)
    controller = MinitouchController(session)
    vars(controller).update(
        _minitouch_port=23456,
        _minitouch_client=SimpleNamespace(close=fail_client_close),
        _minitouch_stream=SimpleNamespace(close=fail_stream_close),
        _minitouch_pid="4312",
        _minitouch_builder=object(),
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        controller.release()

    assert raised.value.exceptions == (client_error, forward_error, stream_error)
    assert vars(controller)["_minitouch_port"] == 0
    assert vars(controller)["_minitouch_client"] is None
    assert vars(controller)["_minitouch_stream"] is None
    assert vars(controller)["_minitouch_pid"] == ""
    assert "_minitouch_builder" not in controller.__dict__


def test_runtime_rejects_mismatched_service_sessions() -> None:
    session = _DeviceSessionDouble()
    mumu_runtime = _MumuRuntimeDouble(_DeviceSessionDouble())

    with pytest.raises(ValueError, match="same ADB session"):
        DeviceRuntime(
            adb_session=session,
            mumu_runtime=cast("MumuRuntime", mumu_runtime),
            capture=_CaptureServiceDouble(mumu_runtime),
            controller=_ControllerServiceDouble(session),
            app_controller=_AppControllerServiceDouble(session),
        )


def test_adb_disconnect_releases_services_before_disconnect() -> None:
    calls: list[str] = []
    connection = object.__new__(Connection)
    connection.serial = "127.0.0.1:16384"
    vars(connection)["_runtime"] = SimpleNamespace(release_serial=lambda: calls.append("release"))
    connection.__dict__["adb_client"] = SimpleNamespace(disconnect=lambda _serial: calls.append("disconnect") or "")

    connection.adb_disconnect()

    assert calls == ["release", "disconnect"]


def test_adb_restart_releases_services_before_killing_server() -> None:
    calls: list[str] = []

    class _Connection(Connection):
        @property
        def adb_client(self) -> SimpleNamespace:
            calls.append("client")
            return SimpleNamespace(server_kill=lambda: calls.append("server_kill"))

        @override
        def adb_start_server(self) -> int:
            calls.append("start_server")
            return 41

    connection = object.__new__(_Connection)
    vars(connection)["_runtime"] = SimpleNamespace(release_serial=lambda: calls.append("release"))

    connection.adb_restart()

    assert calls == ["release", "client", "server_kill", "start_server"]


class _RecoveryLogger:
    def __init__(self) -> None:
        self.exceptions: list[Exception] = []

    def exception(self, error: Exception) -> None:
        self.exceptions.append(error)

    def info(self, _message: object) -> None:
        pass


def _failing_runtime(calls: list[str], error: Exception) -> SimpleNamespace:
    def release_serial() -> None:
        calls.append("release")
        raise error

    return SimpleNamespace(release_serial=release_serial)


def test_adb_disconnect_continues_after_runtime_cleanup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    error = AdbError("old forward")
    logger = _RecoveryLogger()
    connection = object.__new__(Connection)
    connection.serial = "127.0.0.1:16384"
    vars(connection)["_runtime"] = _failing_runtime(calls, error)
    vars(connection)["adb_client"] = SimpleNamespace(disconnect=lambda _serial: calls.append("disconnect") or "")
    monkeypatch.setattr(connection_module, "logger", logger)

    connection.adb_disconnect()

    assert calls == ["release", "disconnect"]
    assert logger.exceptions == [error]


def test_adb_restart_rebuilds_client_after_runtime_cleanup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    error = AdbError("old forward")
    logger = _RecoveryLogger()
    old_client = SimpleNamespace(server_kill=lambda: calls.append("server_kill"))
    new_client = object()

    class _RestartConnection(Connection):
        @cached_property
        @override
        def adb_client(self) -> object:
            calls.append("rebuild_client")
            return new_client

        @override
        def adb_start_server(self) -> int:
            calls.append("start_server")
            _ = self.adb_client
            return 41

    connection = object.__new__(_RestartConnection)
    vars(connection).update(
        _runtime=_failing_runtime(calls, error),
        adb_client=old_client,
    )
    monkeypatch.setattr(connection_module, "logger", logger)

    connection.adb_restart()

    assert calls == ["release", "server_kill", "start_server", "rebuild_client"]
    assert connection.adb_client is new_client
    assert logger.exceptions == [error]


def test_bind_serial_publishes_new_serial_after_runtime_cleanup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    error = AdbError("old forward")
    logger = _RecoveryLogger()
    old_serial = "127.0.0.1:16384"
    new_serial = "127.0.0.1:16385"
    connection = object.__new__(Connection)
    connection.serial = old_serial
    connection.config = SimpleNamespace(Emulator_Serial=old_serial)
    vars(connection).update(
        _runtime=_failing_runtime(calls, error),
        port=16384,
        adb=object(),
    )
    monkeypatch.setattr(connection_module, "logger", logger)

    assert connection.bind_serial(new_serial)

    assert calls == ["release"]
    assert connection.serial == new_serial
    assert "port" not in vars(connection)
    assert "adb" not in vars(connection)
    assert logger.exceptions == [error]
