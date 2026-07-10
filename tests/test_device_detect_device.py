from types import SimpleNamespace

from module.device.connection import Connection
from module.map.map_grids import SelectedGrids

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
}


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
    device_batches: list[list[object]],
):
    connection = object.__new__(Connection)
    connection.serial = serial
    connection.config = SimpleNamespace(Emulator_Serial=serial)
    connection.device_batches = list(device_batches)
    connection.last_devices = []
    connection.list_calls = 0

    def list_device():
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
    connection = _make_connection(
        serial="127.0.0.1:16384",
        device_batches=[[_mumu12("127.0.0.1:16385")]],
    )
    connection.__dict__.update(
        port=16384,
        is_mumu12_family=True,
        is_mumu_family=True,
        adb=object(),
        emulator_instance=object(),
        nemud_app_keep_alive="false",
        nemud_player_version="3.8.27.2950",
        is_mumu_over_version_400=False,
        is_mumu_over_version_356=True,
    )

    connection.detect_device()

    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert connection.serial == "127.0.0.1:16385"
    assert _SERIAL_BOUND_CACHES.isdisjoint(connection.__dict__)
