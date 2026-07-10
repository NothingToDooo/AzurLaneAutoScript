import threading
from types import SimpleNamespace

import pytest
from adbutils.errors import AdbError

from module.base.decorator import cached_property
from module.device import connection as connection_module
from module.device.app_control import AppControl
from module.device.connection import Connection
from module.device.control import Control
from module.device.device import Device
from module.device.method.minitouch import Minitouch
from module.device.method.nemu_ipc import NemuIpc
from module.device.minitouch_service import MinitouchController
from module.device.platform.platform_base import PlatformBase
from module.device.platform.platform_windows import PlatformWindows
from module.device.runtime import DeviceRuntime
from module.device.screenshot import Screenshot
from module.exception import EmulatorNotRunningError


class _NoIoSession:
    def __getattr__(self, name: str) -> object:
        message = f"服务构造期间不应读取 session.{name}"
        raise AssertionError(message)


def test_runtime_services_share_one_adb_session_without_constructor_io() -> None:
    session = _NoIoSession()

    runtime = DeviceRuntime.create(session)

    assert runtime.adb_session is session
    assert runtime.mumu_runtime.session is session
    assert runtime.controller.session is session
    assert runtime.app_controller.session is session
    assert runtime.capture.mumu_runtime is runtime.mumu_runtime


def test_device_mro_keeps_one_connection_spine() -> None:
    mro = Device.__mro__

    assert mro[:4] == (Device, Screenshot, Control, Connection)
    assert mro.count(Connection) == 1
    for legacy_base in (AppControl, Minitouch, NemuIpc, PlatformBase, PlatformWindows):
        assert legacy_base not in mro


def test_device_builds_runtime_before_first_connection_and_reuses_it_for_recovery(monkeypatch) -> None:
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
        controller=SimpleNamespace(early_init=lambda: None),
        app_controller=object(),
    )

    def create(adb_session):
        runtime.adb_session = adb_session
        return runtime

    def connection_init(device, config) -> None:
        attempts.append((id(device.runtime), device.runtime.adb_session))
        device.config = config
        if len(attempts) < 4:
            raise EmulatorNotRunningError

    config = SimpleNamespace(is_actual_task=False)
    monkeypatch.setattr(DeviceRuntime, "create", staticmethod(create))
    monkeypatch.setattr(Connection, "__init__", connection_init)
    monkeypatch.setattr(Device, "method_check", lambda _device: None)
    monkeypatch.setattr(Device, "screenshot_interval_set", lambda _device: None)

    device = Device(config)

    assert len(attempts) == 4
    assert {runtime_id for runtime_id, _ in attempts} == {id(runtime)}
    assert all(session is device for _, session in attempts)
    assert starts == [runtime.mumu_runtime] * 3


def test_runtime_releases_serial_services_in_explicit_order() -> None:
    calls: list[str] = []
    session = object()
    mumu_runtime = SimpleNamespace(session=session, invalidate_serial=lambda: calls.append("mumu"))
    runtime = DeviceRuntime(
        adb_session=session,
        mumu_runtime=mumu_runtime,
        capture=SimpleNamespace(mumu_runtime=mumu_runtime, release=lambda: calls.append("capture")),
        controller=SimpleNamespace(session=session, release=lambda: calls.append("controller")),
        app_controller=SimpleNamespace(session=session),
    )

    runtime.release_serial()
    runtime.release_serial()

    assert calls == ["controller", "capture", "mumu", "controller", "capture", "mumu"]


def test_runtime_finishes_capture_and_mumu_cleanup_after_controller_error() -> None:
    calls: list[str] = []
    session = object()
    mumu_runtime = SimpleNamespace(session=session, invalidate_serial=lambda: calls.append("mumu"))

    def fail_controller() -> None:
        calls.append("controller")
        message = "forward failed"
        raise OSError(message)

    runtime = DeviceRuntime(
        adb_session=session,
        mumu_runtime=mumu_runtime,
        capture=SimpleNamespace(mumu_runtime=mumu_runtime, release=lambda: calls.append("capture")),
        controller=SimpleNamespace(session=session, release=fail_controller),
        app_controller=SimpleNamespace(session=session),
    )

    with pytest.raises(OSError, match="forward failed"):
        runtime.release_serial()

    assert calls == ["controller", "capture", "mumu"]


def test_minitouch_release_clears_state_when_forward_removal_fails() -> None:
    closed: list[str] = []
    session = SimpleNamespace(
        adb_forward_remove=lambda _local: (_ for _ in ()).throw(OSError("remove failed")),
    )
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


def test_minitouch_release_does_not_join_current_initialization_thread() -> None:
    controller = MinitouchController(SimpleNamespace())
    vars(controller)["_minitouch_init_thread"] = threading.current_thread()

    controller.release()

    assert vars(controller)["_minitouch_init_thread"] is None


def test_release_during_wait_only_releases_capture() -> None:
    calls: list[str] = []
    device = object.__new__(Device)
    vars(device)["_runtime"] = SimpleNamespace(
        capture=SimpleNamespace(release=lambda: calls.append("capture")),
        controller=SimpleNamespace(release=lambda: calls.append("controller")),
    )

    device.release_during_wait()

    assert calls == ["capture"]


def test_device_facade_delegates_to_owned_services() -> None:
    device = object.__new__(Device)
    vars(device)["_runtime"] = SimpleNamespace(
        app_controller=SimpleNamespace(
            current=lambda: "current",
            is_running=lambda: True,
            start=lambda: "started",
            stop=lambda: "stopped",
        ),
        controller=SimpleNamespace(click=lambda *args: ("click", args)),
        capture=SimpleNamespace(screenshot=lambda: "image", release=lambda: None),
    )
    device.config = SimpleNamespace(Error_HandleError=True)
    device.stuck_record_clear = lambda: None
    device.click_record_clear = lambda: None

    assert device.app_current() == "current"
    assert device.app_is_running() is True
    assert device.app_start() == "started"
    assert device.app_stop() == "stopped"
    assert device.click_minitouch(1, 2) == ("click", (1, 2))
    assert device.screenshot_nemu_ipc() == "image"


def test_runtime_rejects_mismatched_service_sessions() -> None:
    session = object()

    with pytest.raises(ValueError, match="same ADB session"):
        DeviceRuntime(
            adb_session=session,
            mumu_runtime=SimpleNamespace(session=object()),
            capture=SimpleNamespace(mumu_runtime=object()),
            controller=SimpleNamespace(session=session),
            app_controller=SimpleNamespace(session=session),
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
        def adb_client(self):
            calls.append("client")
            return SimpleNamespace(server_kill=lambda: calls.append("server_kill"))

    connection = object.__new__(_Connection)
    vars(connection)["_runtime"] = SimpleNamespace(release_serial=lambda: calls.append("release"))

    connection.adb_restart()

    assert calls[:3] == ["release", "client", "server_kill"]


class _RecoveryLogger:
    def __init__(self) -> None:
        self.exceptions: list[Exception] = []

    def exception(self, error: Exception) -> None:
        self.exceptions.append(error)

    def info(self, _message: object) -> None:
        pass


def _failing_runtime(calls: list[str], error: Exception):
    def release_serial() -> None:
        calls.append("release")
        raise error

    return SimpleNamespace(release_serial=release_serial)


def test_adb_disconnect_continues_after_runtime_cleanup_error(monkeypatch) -> None:
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


def test_adb_restart_rebuilds_client_after_runtime_cleanup_error(monkeypatch) -> None:
    calls: list[str] = []
    error = AdbError("old forward")
    logger = _RecoveryLogger()
    old_client = SimpleNamespace(server_kill=lambda: calls.append("server_kill"))
    new_client = object()

    class _RestartConnection(Connection):
        @cached_property
        def adb_client(self):
            calls.append("rebuild_client")
            return new_client

    connection = object.__new__(_RestartConnection)
    vars(connection).update(
        _runtime=_failing_runtime(calls, error),
        adb_client=old_client,
    )
    monkeypatch.setattr(connection_module, "logger", logger)

    connection.adb_restart()

    assert calls == ["release", "server_kill", "rebuild_client"]
    assert connection.adb_client is new_client
    assert logger.exceptions == [error]


def test_bind_serial_publishes_new_serial_after_runtime_cleanup_error(monkeypatch) -> None:
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
