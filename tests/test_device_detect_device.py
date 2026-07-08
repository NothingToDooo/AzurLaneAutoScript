from types import SimpleNamespace

import pytest

from module.device.connection import Connection
from module.exception import RequestHumanTakeover
from module.map.map_grids import SelectedGrids


def _device(serial: str, *, status: str = "device", may_mumu12_family: bool = False, port: int = 0):
    return SimpleNamespace(
        serial=serial,
        status=status,
        may_mumu12_family=may_mumu12_family,
        port=port,
    )


def _mumu12(serial: str):
    return _device(serial, may_mumu12_family=True, port=int(serial.split(":")[1]))


def _make_connection(
    *,
    serial: str,
    emulator_serial: str | None = None,
    device_batches: list[list[object]],
):
    connection = object.__new__(Connection)
    connection.serial = serial
    connection.config = SimpleNamespace(Emulator_Serial=emulator_serial or serial)
    connection.device_batches = list(device_batches)
    connection.last_devices: list[object] = []
    connection.list_calls = 0
    connection.brute_force_calls: list[list[str]] = []

    def list_device():
        connection.list_calls += 1
        if connection.device_batches:
            connection.last_devices = connection.device_batches.pop(0)
        return SelectedGrids(connection.last_devices)

    def adb_brute_force_connect(serial_list: list[str]) -> None:
        connection.brute_force_calls.append(serial_list)

    connection.list_device = list_device
    connection.adb_brute_force_connect = adb_brute_force_connect
    return connection


def _patch_emulator_manager(monkeypatch: pytest.MonkeyPatch, serials: list[str]) -> None:
    class _EmulatorManager:
        all_emulator_serials = serials

    def import_module(name: str):
        assert name == "module.device.platform.emulator_windows"
        return SimpleNamespace(EmulatorManager=_EmulatorManager)

    monkeypatch.setattr("module.device.connection.import_module", import_module)


def test_detect_device_auto_brute_forces_before_using_only_available_device(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_emulator_manager(monkeypatch, ["127.0.0.1:16384"])
    connection = _make_connection(
        serial="auto",
        emulator_serial="auto",
        device_batches=[
            [],
            [_mumu12("127.0.0.1:16384")],
        ],
    )

    connection.detect_device()

    assert connection.brute_force_calls == [["127.0.0.1:16384"]]
    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert connection.serial == "127.0.0.1:16384"


def test_detect_device_auto_prefers_mumu12_port_over_7555() -> None:
    connection = _make_connection(
        serial="auto",
        emulator_serial="auto",
        device_batches=[
            [
                _device("127.0.0.1:7555"),
                _mumu12("127.0.0.1:16384"),
            ]
        ],
    )

    connection.detect_device()

    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert connection.serial == "127.0.0.1:16384"


def test_detect_device_auto_rejects_multiple_available_devices() -> None:
    connection = _make_connection(
        serial="auto",
        emulator_serial="auto",
        device_batches=[
            [
                _mumu12("127.0.0.1:16384"),
                _mumu12("127.0.0.1:16416"),
            ]
        ],
    )

    with pytest.raises(RequestHumanTakeover):
        connection.detect_device()


def test_detect_device_redirects_7555_to_mumu12_port() -> None:
    connection = _make_connection(
        serial="127.0.0.1:7555",
        device_batches=[
            [
                _device("127.0.0.1:7555"),
                _mumu12("127.0.0.1:16384"),
            ]
        ],
    )

    connection.detect_device()

    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert connection.serial == "127.0.0.1:16384"


def test_detect_device_updates_runtime_serial_for_shifted_mumu12_port_only() -> None:
    connection = _make_connection(
        serial="127.0.0.1:16384",
        device_batches=[[_mumu12("127.0.0.1:16385")]],
    )

    connection.detect_device()

    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert connection.serial == "127.0.0.1:16385"
