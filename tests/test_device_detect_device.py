from types import SimpleNamespace

from module.device.connection import Connection
from module.map.map_grids import SelectedGrids


def _device(
    serial: str,
    *,
    status: str = "device",
    may_mumu12_family: bool = False,
    port: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        serial=serial,
        status=status,
        may_mumu12_family=may_mumu12_family,
        port=port,
    )


def _mumu12(serial: str) -> SimpleNamespace:
    return _device(serial, may_mumu12_family=True, port=int(serial.split(":")[1]))


def _make_connection(
    *,
    serial: str,
    device_batches: list[list[SimpleNamespace]],
) -> Connection:
    connection = object.__new__(Connection)
    connection.serial = serial
    connection.config = SimpleNamespace(Emulator_Serial=serial)
    connection.device_batches = list(device_batches)
    connection.last_devices = []
    connection.list_calls = 0

    def list_device() -> SelectedGrids[SimpleNamespace]:
        connection.list_calls += 1
        if connection.device_batches:
            connection.last_devices = connection.device_batches.pop(0)
        return SelectedGrids(connection.last_devices)

    connection.list_device = list_device
    return connection


def test_detect_device_keeps_configured_mumu12_serial_when_alias_is_visible() -> None:
    connection = _make_connection(
        serial="127.0.0.1:16384",
        device_batches=[[_device("emulator-5554"), _mumu12("127.0.0.1:16384")]],
    )

    connection.detect_device()

    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert connection.serial == "127.0.0.1:16384"


def test_detect_device_keeps_configured_serial_when_multiple_mumu12_ports_are_visible() -> None:
    connection = _make_connection(
        serial="127.0.0.1:16384",
        device_batches=[
            [
                _mumu12("127.0.0.1:16384"),
                _mumu12("127.0.0.1:16416"),
            ]
        ],
    )

    connection.detect_device()

    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert connection.serial == "127.0.0.1:16384"


def test_detect_device_updates_runtime_serial_for_shifted_mumu12_port_only() -> None:
    old_serial = "127.0.0.1:16384"
    new_serial = "127.0.0.1:16385"
    connection = _make_connection(
        serial=old_serial,
        device_batches=[[_mumu12(new_serial)]],
    )
    properties = {
        old_serial: {"ro.product.cpu.abi": "arm64-v8a", "ro.build.version.sdk": "28"},
        new_serial: {"ro.product.cpu.abi": "x86_64", "ro.build.version.sdk": "35"},
    }
    connection.__dict__["adb_client"] = object()
    connection.__dict__["adb_getprop"] = lambda name: properties[connection.serial][name]
    old_adb = connection.adb
    assert connection.cpu_abi == "arm64-v8a"
    assert connection.sdk_ver == 28

    connection.detect_device()

    assert connection.config.Emulator_Serial == old_serial
    assert connection.serial == new_serial
    assert connection.adb is not old_adb
    assert connection.adb.serial == new_serial
    assert connection.port == 16385
    assert connection.cpu_abi == "x86_64"
    assert connection.sdk_ver == 35
