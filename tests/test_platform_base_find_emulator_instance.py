from types import SimpleNamespace

from module.device.platform.platform_base import PlatformBase, serial_to_id


def _instance(
    *,
    serial: str = "127.0.0.1:16384",
    name: str = "MuMuPlayer-12.0-0",
    path: str = "C:/MuMu/shell/MuMuPlayer.exe",
    emulator_type: str = "MuMuPlayer12",
    mumu_id: int | None = None,
):
    return SimpleNamespace(
        serial=serial,
        name=name,
        path=path,
        type=emulator_type,
        MuMuPlayer12_id=mumu_id,
    )


def _make_platform(
    *,
    instances: list[object],
    serial: str = "127.0.0.1:16384",
    running: list[str] | None = None,
):
    platform = object.__new__(PlatformBase)
    platform.serial = serial
    platform.all_emulator_instances = instances
    platform.running = running or []
    platform.running_calls = 0

    def iter_running_emulator():
        platform.running_calls += 1
        return iter(platform.running)

    platform.iter_running_emulator = iter_running_emulator
    return platform


def test_serial_to_id_accepts_mumu12_neighbor_ports() -> None:
    assert serial_to_id("127.0.0.1:16384") == 0
    assert serial_to_id("127.0.0.1:16385") == 0
    assert serial_to_id("127.0.0.1:16416") == 1
    assert serial_to_id("emulator-5554") is None
    assert serial_to_id("127.0.0.1:7555") is None


def test_find_emulator_instance_returns_unique_serial_match() -> None:
    expected = _instance(serial="127.0.0.1:16384")
    platform = _make_platform(
        instances=[
            expected,
            _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-1"),
        ]
    )

    assert platform.find_emulator_instance("127.0.0.1:16384") is expected


def test_find_emulator_instance_returns_none_when_serial_missing() -> None:
    platform = _make_platform(
        instances=[
            _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-1"),
        ],
        running=["C:/MuMu/shell/MuMuPlayer.exe"],
    )

    assert platform.find_emulator_instance("127.0.0.1:16384") is None
    assert platform.running_calls == 0


def test_find_emulator_instance_uses_mumu12_id_to_disambiguate_duplicate_serial() -> None:
    expected = _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-1", mumu_id=1)
    platform = _make_platform(
        serial="127.0.0.1:16416",
        instances=[
            _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-0", mumu_id=0),
            expected,
        ],
    )

    assert platform.find_emulator_instance("127.0.0.1:16416") is expected


def test_emulator_instance_uses_runtime_discovery_without_config_cache() -> None:
    expected = _instance(serial="127.0.0.1:16384")
    platform = _make_platform(
        instances=[
            expected,
        ],
    )

    assert platform.emulator_instance is expected


def test_find_emulator_instance_falls_back_to_single_running_path() -> None:
    expected = _instance(serial="127.0.0.1:16384", name="ArkNights", path="C:/B/MuMuPlayer.exe")
    platform = _make_platform(
        instances=[
            _instance(serial="127.0.0.1:16384", name="Default", path="C:/A/MuMuPlayer.exe"),
            expected,
        ],
        running=["C:/B/MuMuPlayer.exe"],
    )

    assert platform.find_emulator_instance("127.0.0.1:16384") is expected
