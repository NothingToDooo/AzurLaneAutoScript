from types import SimpleNamespace

import pytest

from module.device.connection_attr import ConnectionAttr
from module.exception import RequestHumanTakeover


def _make_attr(serial: str):
    attr = object.__new__(ConnectionAttr)
    attr.config = SimpleNamespace(Emulator_Serial=serial)
    attr.serial = serial
    return attr


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
