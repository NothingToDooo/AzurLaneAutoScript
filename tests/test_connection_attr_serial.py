from types import SimpleNamespace

import pytest

from module.device.connection_attr import ConnectionAttr
from module.device.device import Device
from module.exception import RequestHumanTakeover

_SERIAL_BOUND_CACHES = {
    "port",
    "is_mumu12_family",
    "is_mumu_family",
    "adb",
    "emulator_instance",
    "nemud_app_keep_alive",
    "nemud_player_version",
    "is_mumu_over_version_400",
    "is_mumu_over_version_356",
    "nemu_ipc",
    "_minitouch_builder",
}


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
    def __init__(self, connection: Device, builder: object):
        self.connection = connection
        self.builder = builder
        self.joined_at: list[str] = []

    def join(self) -> None:
        self.joined_at.append(self.connection.serial)
        self.connection.__dict__["_minitouch_builder"] = self.builder


def _make_attr(serial: str):
    attr = object.__new__(ConnectionAttr)
    attr.config = SimpleNamespace(Emulator_Serial=serial)
    attr.serial = serial
    return attr


def _make_connection(serial: str) -> Device:
    connection = object.__new__(Device)
    connection.config = SimpleNamespace(Emulator_Serial=serial)
    connection.serial = serial
    return connection


def _prime_serial_bound_state(connection: Device):
    client = _Closeable(connection)
    stream = _Closeable(connection)
    nemu_ipc = _NemuIpc(connection)
    forward_removals: list[tuple[str, str]] = []

    connection.__dict__.update(
        port=int(connection.serial.rsplit(":", 1)[-1]),
        is_mumu12_family=True,
        is_mumu_family=True,
        adb=SimpleNamespace(serial=connection.serial),
        emulator_instance=object(),
        nemud_app_keep_alive="false",
        nemud_player_version="3.8.27.2950",
        is_mumu_over_version_400=False,
        is_mumu_over_version_356=True,
        nemu_ipc=nemu_ipc,
        _minitouch_port=23456,
        _minitouch_client=client,
        _minitouch_stream=stream,
        _minitouch_builder=object(),
    )
    connection.__dict__["adb_forward_remove"] = lambda local: forward_removals.append((local, connection.serial))
    return SimpleNamespace(
        client=client,
        stream=stream,
        nemu_ipc=nemu_ipc,
        forward_removals=forward_removals,
    )


def _assert_serial_bound_state_released(connection: Device, state, *, old_serial: str) -> None:
    assert _SERIAL_BOUND_CACHES.isdisjoint(connection.__dict__)
    assert connection.__dict__["_minitouch_port"] == 0
    assert connection.__dict__["_minitouch_client"] is None
    assert connection.__dict__["_minitouch_stream"] is None
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
    connection.__dict__.pop("_minitouch_builder")
    old_builder = object()
    init_thread = _MinitouchInitThread(connection, old_builder)
    connection.__dict__["_minitouch_init_thread"] = init_thread

    connection.bind_serial("127.0.0.1:16385")

    assert init_thread.joined_at == [old_serial]
    assert connection.__dict__["_minitouch_init_thread"] is None
    assert "_minitouch_builder" not in connection.__dict__
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
