from types import SimpleNamespace

import pytest

from module.device import connection_attr as connection_attr_module
from module.device.connection_attr import ConnectionAttr
from module.device.device import Device
from module.device.runtime import DeviceRuntime
from module.exception import RequestHumanTakeover


class _Closeable:
    def __init__(self, connection: Device):
        self.connection = connection
        self.closed_at: list[str] = []

    def close(self) -> None:
        self.closed_at.append(self.connection.serial)


class _NemuIpc:
    def __init__(self, connection: Device):
        self.connection = connection
        self.disconnected_at: list[str] = []

    def disconnect(self) -> None:
        self.disconnected_at.append(self.connection.serial)


class _MinitouchInitThread:
    def __init__(self, connection: Device, controller, builder: object):
        self.connection = connection
        self.controller = controller
        self.builder = builder
        self.joined_at: list[str] = []

    def join(self) -> None:
        self.joined_at.append(self.connection.serial)
        self.controller.__dict__["_minitouch_builder"] = self.builder


def _make_attr(serial: str):
    attr = object.__new__(ConnectionAttr)
    attr.config = SimpleNamespace(Emulator_Serial=serial)
    attr.serial = serial
    return attr


def _make_connection(serial: str) -> Device:
    connection = object.__new__(Device)
    connection.config = SimpleNamespace(Emulator_Serial=serial)
    connection.serial = serial
    vars(connection)["_runtime"] = DeviceRuntime.create(connection)
    return connection


def _prime_serial_bound_state(connection: Device):
    client = _Closeable(connection)
    stream = _Closeable(connection)
    nemu_ipc = _NemuIpc(connection)
    forward_removals: list[tuple[str, str]] = []

    controller = connection.controller
    controller.__dict__.update(
        _minitouch_port=23456,
        _minitouch_client=client,
        _minitouch_stream=stream,
        _minitouch_pid="4312",
        _minitouch_builder=object(),
    )
    connection.capture.__dict__["nemu_ipc"] = nemu_ipc
    connection.__dict__["adb_forward_remove"] = lambda local: forward_removals.append((local, connection.serial))
    return SimpleNamespace(
        client=client,
        stream=stream,
        nemu_ipc=nemu_ipc,
        forward_removals=forward_removals,
    )


def _assert_serial_bound_state_released(connection: Device, state, *, old_serial: str) -> None:
    controller = connection.controller
    assert vars(controller)["_minitouch_port"] == 0
    assert vars(controller)["_minitouch_client"] is None
    assert vars(controller)["_minitouch_stream"] is None
    assert vars(controller)["_minitouch_pid"] == ""
    assert "_minitouch_builder" not in controller.__dict__
    assert "nemu_ipc" not in connection.capture.__dict__
    assert state.client.closed_at == [old_serial]
    assert state.stream.closed_at == [old_serial]
    assert state.nemu_ipc.disconnected_at == [old_serial]
    assert state.forward_removals == [("tcp:23456", old_serial)]


def test_bind_serial_invalidates_runtime_state_without_persisting_config() -> None:
    old_serial = "127.0.0.1:16384"
    connection = _make_connection(old_serial)
    state = _prime_serial_bound_state(connection)

    changed = connection.bind_serial("127.0.0.1:16385")

    assert changed is True
    assert connection.serial == "127.0.0.1:16385"
    assert connection.config.Emulator_Serial == old_serial
    _assert_serial_bound_state_released(connection, state, old_serial=old_serial)


def test_bind_serial_same_serial_has_no_side_effects() -> None:
    serial = "127.0.0.1:16384"
    connection = _make_connection(serial)
    state = _prime_serial_bound_state(connection)
    before = connection.__dict__.copy()

    changed = connection.bind_serial(serial, persist=True)

    assert changed is False
    assert connection.__dict__ == before
    assert state.client.closed_at == []
    assert state.stream.closed_at == []
    assert state.nemu_ipc.disconnected_at == []
    assert state.forward_removals == []


def test_bind_serial_persists_explicit_change() -> None:
    connection = _make_connection("127.0.0.1:16384")

    changed = connection.bind_serial("127.0.0.1:16385", persist=True)

    assert changed is True
    assert connection.serial == "127.0.0.1:16385"
    assert connection.config.Emulator_Serial == "127.0.0.1:16385"


def test_bind_serial_recomputes_each_layer_from_new_serial(monkeypatch) -> None:
    old_serial = "127.0.0.1:16384"
    new_serial = "127.0.0.1:16385"
    connection = _make_connection(old_serial)
    family_checks: list[str] = []
    properties = {
        old_serial: {"ro.product.cpu.abi": "arm64-v8a", "ro.build.version.sdk": "28"},
        new_serial: {"ro.product.cpu.abi": "x86_64", "ro.build.version.sdk": "35"},
    }

    def is_mumu12_serial(serial: str) -> bool:
        family_checks.append(serial)
        return True

    monkeypatch.setattr(connection_attr_module, "is_mumu12_serial", is_mumu12_serial)
    connection.__dict__["adb_client"] = object()
    connection.__dict__["adb_getprop"] = lambda name: properties[connection.serial][name]
    connection.mumu_runtime.__dict__["find_emulator_instance"] = lambda serial: SimpleNamespace(serial=serial)

    old_adb = connection.adb
    assert connection.port == 16384
    assert connection.is_mumu_family is True
    assert connection.cpu_abi == "arm64-v8a"
    assert connection.sdk_ver == 28
    old_instance = connection.emulator_instance
    assert old_instance is not None
    assert old_instance.serial == old_serial

    connection.bind_serial(new_serial)

    assert connection.adb is not old_adb
    assert connection.adb.serial == new_serial
    assert connection.port == 16385
    assert connection.is_mumu_family is True
    assert connection.cpu_abi == "x86_64"
    assert connection.sdk_ver == 35
    new_instance = connection.emulator_instance
    assert new_instance is not None
    assert new_instance.serial == new_serial
    assert family_checks == [old_serial, new_serial]


def test_serial_check_revises_through_persistent_rebinding() -> None:
    old_serial = "16384"
    connection = _make_connection(old_serial)
    state = _prime_serial_bound_state(connection)

    connection.serial_check()

    assert connection.serial == "127.0.0.1:16384"
    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    _assert_serial_bound_state_released(connection, state, old_serial=old_serial)


def test_bind_serial_repeated_release_is_safe() -> None:
    old_serial = "127.0.0.1:16384"
    connection = _make_connection(old_serial)
    state = _prime_serial_bound_state(connection)

    assert connection.bind_serial("127.0.0.1:16385") is True
    assert connection.bind_serial("127.0.0.1:16386") is True

    assert connection.serial == "127.0.0.1:16386"
    _assert_serial_bound_state_released(connection, state, old_serial=old_serial)


def test_bind_serial_joins_old_minitouch_initialization_before_releasing_builder() -> None:
    old_serial = "127.0.0.1:16384"
    connection = _make_connection(old_serial)
    state = _prime_serial_bound_state(connection)
    connection.controller.__dict__.pop("_minitouch_builder")
    old_builder = object()
    init_thread = _MinitouchInitThread(connection, connection.controller, old_builder)
    vars(connection.controller)["_minitouch_init_thread"] = init_thread

    connection.bind_serial("127.0.0.1:16385")

    assert init_thread.joined_at == [old_serial]
    assert vars(connection.controller)["_minitouch_init_thread"] is None
    assert "_minitouch_builder" not in connection.controller.__dict__
    _assert_serial_bound_state_released(connection, state, old_serial=old_serial)


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("16384", "127.0.0.1:16384"),
        ("127.0.0.1.16384", "127.0.0.1:16384"),
        ("MuMu模拟器12127.0.0.1:16384", "127.0.0.1:16384"),
    ],
)
def test_serial_check_revises_common_mumu12_serial_typos(serial: str, expected: str) -> None:
    attr = _make_attr(serial)

    attr.serial_check()

    assert attr.serial == expected
    assert attr.config.Emulator_Serial == expected


@pytest.mark.parametrize(
    "serial",
    [
        "auto",
        "emulator-5554",
        "127.0.0.1:5555",
        "127.0.0.1:7555",
        "127.0.0.1:17408",
        "192.168.1.2:16384",
    ],
)
def test_serial_check_rejects_non_mumu12_tcp_serial(serial: str) -> None:
    attr = _make_attr(serial)

    with pytest.raises(RequestHumanTakeover):
        attr.serial_check()
