from types import SimpleNamespace

import pytest

from module.device.connection import Connection
from module.exception import EmulatorNotRunningError, RequestHumanTakeover


class _AdbClient:
    def __init__(self, messages: list[str] | None = None) -> None:
        self.messages = messages or []
        self.connect_calls: list[str] = []
        self.disconnect_calls: list[str] = []

    def connect(self, serial: str) -> str:
        self.connect_calls.append(serial)
        if self.messages:
            return self.messages.pop(0)
        return ""

    def disconnect(self, serial: str) -> str:
        self.disconnect_calls.append(serial)
        return f"disconnected {serial}"


class _DiagnosticConnection(Connection):
    adb_client: _AdbClient
    devices: list[SimpleNamespace]
    detect_calls: int
    brute_force_calls: list[list[str]]
    refused_diagnose_calls: int

    def _diagnose_adb_connect_refused(self) -> None:
        self.refused_diagnose_calls += 1


def _device(serial: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(serial=serial, status=status)


def _make_connection(
    *,
    serial: str = "127.0.0.1:16384",
    devices: list[SimpleNamespace] | None = None,
    connect_messages: list[str] | None = None,
    detect_serial: str | None = None,
) -> _DiagnosticConnection:
    connection = object.__new__(_DiagnosticConnection)
    connection.serial = serial
    connection.adb_client = _AdbClient(connect_messages)
    connection.devices = devices or []
    connection.detect_calls = 0
    connection.brute_force_calls = []
    connection.refused_diagnose_calls = 0

    def list_device() -> list[SimpleNamespace]:
        return connection.devices

    def detect_device() -> None:
        connection.detect_calls += 1
        if detect_serial is not None:
            connection.serial = detect_serial

    def adb_brute_force_connect(serial_list: list[str]) -> None:
        connection.brute_force_calls.append(serial_list)

    connection.list_device = list_device
    connection.detect_device = detect_device
    connection.adb_brute_force_connect = adb_brute_force_connect
    return connection


def test_adb_connect_disconnects_offline_devices_before_connecting() -> None:
    connection = _make_connection(
        devices=[_device("127.0.0.1:16384", "offline")],
        connect_messages=["connected to 127.0.0.1:16384"],
    )

    assert connection.adb_connect()
    assert connection.adb_client.disconnect_calls == ["127.0.0.1:16384"]
    assert connection.adb_client.connect_calls == ["127.0.0.1:16384"]


@pytest.mark.parametrize(
    "serial",
    [
        "emulator-5554",
        "abcdef123456",
        "auto",
        "192.168.1.2:5555",
        "127.0.0.1:5555",
        "127.0.0.1:7555",
        "127.0.0.1:17408",
    ],
)
def test_adb_connect_rejects_non_mumu_tcp_serial(serial: str) -> None:
    connection = _make_connection(serial=serial)

    with pytest.raises(RequestHumanTakeover):
        connection.adb_connect()
    assert connection.adb_client.connect_calls == []


def test_adb_connect_returns_true_when_tcp_connect_succeeds() -> None:
    connection = _make_connection(connect_messages=["already connected to 127.0.0.1:16384"])

    assert connection.adb_connect()
    assert connection.adb_client.connect_calls == ["127.0.0.1:16384"]


def test_adb_connect_rejects_bad_port() -> None:
    connection = _make_connection(connect_messages=["bad port number '99999'"])

    with pytest.raises(RequestHumanTakeover):
        connection.adb_connect()


def test_adb_connect_recovers_mumu12_shifted_port() -> None:
    connection = _make_connection(
        connect_messages=["cannot connect to 127.0.0.1:16384: (10061)"],
        detect_serial="127.0.0.1:16385",
    )

    assert connection.adb_connect()
    assert connection.brute_force_calls == [
        [
            "127.0.0.1:16385",
            "127.0.0.1:16383",
            "127.0.0.1:16386",
            "127.0.0.1:16382",
        ]
    ]
    assert connection.detect_calls == 1
    assert connection.refused_diagnose_calls == 0


def test_adb_connect_runs_refused_diagnostics_before_reporting_missing_device() -> None:
    connection = _make_connection(
        connect_messages=["cannot connect to 127.0.0.1:16384: (10061)"],
    )

    with pytest.raises(EmulatorNotRunningError):
        connection.adb_connect()

    assert connection.refused_diagnose_calls == 1
    assert connection.detect_calls == 1


def test_connection_release_resource_is_base_hook() -> None:
    connection = object.__new__(Connection)
    marker = object()
    connection.__dict__["_minitouch_builder"] = marker

    connection.release_resource()

    assert connection.__dict__["_minitouch_builder"] is marker


class _ReconnectConnection(Connection):
    devices: list[object]
    calls: list[str]


def _make_reconnect_connection(devices: list[object]) -> _ReconnectConnection:
    connection = object.__new__(_ReconnectConnection)
    connection.devices = devices
    connection.calls = []

    def list_device() -> list[object]:
        connection.calls.append("list_device")
        return connection.devices

    def adb_restart() -> None:
        connection.calls.append("adb_restart")

    def adb_disconnect() -> None:
        connection.calls.append("adb_disconnect")

    def adb_connect() -> bool:
        connection.calls.append("adb_connect")
        return True

    def detect_device() -> None:
        connection.calls.append("detect_device")

    connection.list_device = list_device
    connection.adb_restart = adb_restart
    connection.adb_disconnect = adb_disconnect
    connection.adb_connect = adb_connect
    connection.detect_device = detect_device
    return connection


def test_adb_reconnect_restarts_adb_when_no_device_is_listed() -> None:
    connection = _make_reconnect_connection([])

    connection.adb_reconnect()

    assert connection.calls == ["list_device", "adb_restart", "adb_connect", "detect_device"]


def test_adb_reconnect_disconnects_current_serial_when_device_exists() -> None:
    connection = _make_reconnect_connection([object()])

    connection.adb_reconnect()

    assert connection.calls == ["list_device", "adb_disconnect", "adb_connect", "detect_device"]
