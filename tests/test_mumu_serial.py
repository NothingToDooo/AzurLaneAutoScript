import pytest

from module.device.mumu import (
    MUMU12_HOST,
    MuMuSerial,
    is_mumu12_serial,
    mumu12_serial_to_id,
    mumu12_shifted_serials,
    revise_mumu12_serial,
)


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("127.0.0.1:16384", 0),
        ("127.0.0.1:16385", 0),
        ("127.0.0.1:16416", 1),
    ],
)
def test_mumu12_serial_parses_instance_id(serial: str, expected: int) -> None:
    parsed = MuMuSerial.parse(serial)

    assert parsed is not None
    assert parsed.value == serial
    assert parsed.instance_id == expected
    assert mumu12_serial_to_id(serial) == expected
    assert is_mumu12_serial(serial)


@pytest.mark.parametrize(
    "serial",
    [
        "emulator-5554",
        "127.0.0.1:7555",
        "127.0.0.1:17408",
        "192.168.1.2:16384",
    ],
)
def test_mumu12_serial_rejects_non_mumu12(serial: str) -> None:
    assert MuMuSerial.parse(serial) is None
    assert mumu12_serial_to_id(serial) is None
    assert not is_mumu12_serial(serial)


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("16384", "127.0.0.1:16384"),
        ("127.0.0.1.16384", "127.0.0.1:16384"),
        ("5555,16384", "127.0.0.1:16384"),
        ("MuMu模拟器12127.0.0.1:16384", "127.0.0.1:16384"),
        ("auto127.0.0.1:16384", "127.0.0.1:16384"),
    ],
)
def test_revise_mumu12_serial_handles_common_typos(serial: str, expected: str) -> None:
    assert revise_mumu12_serial(serial) == expected


def test_mumu12_shifted_serials_uses_neighbor_ports() -> None:
    assert mumu12_shifted_serials("127.0.0.1:16384") == [
        f"{MUMU12_HOST}:16385",
        f"{MUMU12_HOST}:16383",
        f"{MUMU12_HOST}:16386",
        f"{MUMU12_HOST}:16382",
    ]


def test_mumu12_shifted_serials_rejects_invalid_serial() -> None:
    assert mumu12_shifted_serials("emulator-5554") == []
