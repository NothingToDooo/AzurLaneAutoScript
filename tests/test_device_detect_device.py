from types import SimpleNamespace

import pytest
from adbutils import AdbClient

from module.device.adb_session import AdbDeviceWithStatus
from module.device.connection import Connection
from module.device.mumu import mumu12_endpoint_candidates
from module.device.mumu_connection import MumuEndpointAmbiguousError, select_mumu_endpoint
from module.exception import EmulatorNotRunningError
from module.map.map_grids import SelectedGrids


class _AdbClient:
    def __init__(self) -> None:
        self.connect_calls: list[str] = []
        self.disconnect_calls: list[str] = []

    def connect(self, serial: str) -> str:
        self.connect_calls.append(serial)
        return f"cannot connect to {serial}: (10061)"

    def disconnect(self, serial: str) -> str:
        self.disconnect_calls.append(serial)
        return f"disconnected {serial}"


class _Connection(Connection):
    events: list[tuple[str, str]]

    def release_resource(self) -> None:
        self.events.append(("cleanup", self.serial))

    def _diagnose_adb_connect_refused(self) -> None:
        self.events.append(("diagnose", self.serial))


def _device(serial: str, status: str = "device") -> AdbDeviceWithStatus:
    return AdbDeviceWithStatus(AdbClient(), serial, status)


def _make_connection(
    device_batches: list[list[AdbDeviceWithStatus]],
    *,
    configured_serial: str = "127.0.0.1:16384",
    live_serial: str | None = None,
) -> tuple[_Connection, _AdbClient, list[tuple[str, str]]]:
    connection = object.__new__(_Connection)
    connection.config = SimpleNamespace(Emulator_Serial=configured_serial)
    connection.serial = live_serial or configured_serial
    client = _AdbClient()
    connection.__dict__["adb_client"] = client
    batches = list(device_batches)
    last_devices: list[AdbDeviceWithStatus] = []
    events: list[tuple[str, str]] = []
    connection.events = events

    def list_device() -> SelectedGrids[AdbDeviceWithStatus]:
        nonlocal last_devices
        if batches:
            last_devices = batches.pop(0)
        return SelectedGrids(last_devices)

    connection.list_device = list_device
    return connection, client, events


def test_select_mumu_endpoint_prefers_canonical_exact_port() -> None:
    devices = [_device("127.0.0.1:16385"), _device("127.0.0.1:16384")]

    assert select_mumu_endpoint("127.0.0.1:16386", devices) == "127.0.0.1:16384"


@pytest.mark.parametrize("port", [16382, 16383, 16385, 16386])
def test_select_mumu_endpoint_accepts_unique_same_instance_neighbor(port: int) -> None:
    serial = f"127.0.0.1:{port}"

    assert select_mumu_endpoint("127.0.0.1:16384", [_device(serial)]) == serial


def test_adb_connect_binds_unique_neighbor_after_cleanup_without_changing_config() -> None:
    configured_serial = "127.0.0.1:16384"
    shifted_serial = "127.0.0.1:16385"
    connection, client, events = _make_connection(
        [[_device(shifted_serial)]],
        configured_serial=configured_serial,
    )

    assert connection.adb_connect()
    assert events == [("cleanup", configured_serial)]
    assert connection.serial == shifted_serial
    assert connection.config.Emulator_Serial == configured_serial
    assert client.connect_calls == []


def test_adb_connect_retries_after_first_sweep_only_displaces_old_server() -> None:
    configured_serial = "127.0.0.1:16384"
    connection, client, events = _make_connection(
        [[], [], [_device(configured_serial)]],
        configured_serial=configured_serial,
    )

    assert connection.adb_connect()
    assert client.connect_calls.count(configured_serial) == 2
    assert connection.serial == configured_serial
    assert events == []


def test_adb_connect_diagnoses_bridge_before_reporting_no_same_instance_endpoint() -> None:
    configured_serial = "127.0.0.1:16384"
    connection, client, events = _make_connection([[], []], configured_serial=configured_serial)

    with pytest.raises(EmulatorNotRunningError, match="configured MuMu instance 0"):
        connection.adb_connect()

    assert events == [("diagnose", configured_serial)]
    assert client.connect_calls == list(mumu12_endpoint_candidates(configured_serial)) * 3


def test_adb_connect_rejects_ambiguous_same_instance_neighbors() -> None:
    connection, client, events = _make_connection(
        [[_device("127.0.0.1:16383"), _device("127.0.0.1:16385")]],
    )

    with pytest.raises(MumuEndpointAmbiguousError, match=r"127\.0\.0\.1:16383, 127\.0\.0\.1:16385"):
        connection.adb_connect()

    assert connection.serial == "127.0.0.1:16384"
    assert client.connect_calls == []
    assert events == []


def test_adb_connect_rejects_endpoint_from_other_instance() -> None:
    other_instance = _device("127.0.0.1:16416")
    other_offline_instance = _device("127.0.0.1:16448", "offline")
    devices = [other_instance, other_offline_instance]
    connection, client, events = _make_connection([devices, devices])

    with pytest.raises(EmulatorNotRunningError, match="configured MuMu instance 0"):
        connection.adb_connect()

    assert connection.serial == "127.0.0.1:16384"
    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert "127.0.0.1:16416" not in client.connect_calls
    assert client.disconnect_calls == []
    assert events == [("diagnose", "127.0.0.1:16384")]


def test_adb_connect_preserves_offline_cleanup_and_unauthorized_diagnostic() -> None:
    offline = _device("127.0.0.1:16384", "offline")
    unauthorized = _device("127.0.0.1:16385", "unauthorized")
    connection, client, _ = _make_connection([[offline, unauthorized], []])

    with pytest.raises(EmulatorNotRunningError):
        connection.adb_connect()

    assert client.disconnect_calls == ["127.0.0.1:16384"]
