from types import SimpleNamespace

import pytest

from module.device.connection import Connection
from module.exception import RequestHumanTakeover


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


def _device(serial: str, status: str):
    return SimpleNamespace(serial=serial, status=status)


def _make_connection(
    *,
    serial: str = "127.0.0.1:16384",
    devices: list[object] | None = None,
    connect_messages: list[str] | None = None,
    detect_serial: str | None = None,
):
    connection = object.__new__(Connection)
    connection.serial = serial
    connection.adb_client = _AdbClient(connect_messages)
    connection.devices = devices or []
    connection.detect_calls = 0
    connection.brute_force_calls = []
    connection.bridge_check_calls = 0

    def list_device():
        return connection.devices

    def detect_device() -> None:
        connection.detect_calls += 1
        if detect_serial is not None:
            connection.serial = detect_serial

    def adb_brute_force_connect(serial_list: list[str]) -> None:
        connection.brute_force_calls.append(serial_list)

    def check_mumu_bridge_network() -> bool:
        connection.bridge_check_calls += 1
        return True

    connection.list_device = list_device
    connection.detect_device = detect_device
    connection.adb_brute_force_connect = adb_brute_force_connect
    connection.check_mumu_bridge_network = check_mumu_bridge_network
    return connection


def test_adb_connect_disconnects_offline_devices_before_connecting() -> None:
    connection = _make_connection(
        devices=[_device("127.0.0.1:16384", "offline")],
        connect_messages=["connected to 127.0.0.1:16384"],
    )

    assert connection.adb_connect()
    assert connection.adb_client.disconnect_calls == ["127.0.0.1:16384"]
    assert connection.adb_client.connect_calls == ["127.0.0.1:16384"]


@pytest.mark.parametrize("serial", ["emulator-5554", "abcdef123456", "auto", "192.168.1.2:5555"])
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
