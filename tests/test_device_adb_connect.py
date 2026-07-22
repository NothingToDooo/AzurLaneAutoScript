from module.device.connection import Connection


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

    connection.list_device = list_device
    connection.adb_restart = adb_restart
    connection.adb_disconnect = adb_disconnect
    connection.adb_connect = adb_connect
    return connection


def test_adb_reconnect_restarts_adb_when_no_device_is_listed() -> None:
    connection = _make_reconnect_connection([])

    connection.adb_reconnect()

    assert connection.calls == ["list_device", "adb_restart", "adb_connect"]


def test_adb_reconnect_disconnects_current_serial_when_device_exists() -> None:
    connection = _make_reconnect_connection([object()])

    connection.adb_reconnect()

    assert connection.calls == ["list_device", "adb_disconnect", "adb_connect"]
