import json
from types import SimpleNamespace

import pytest

from module.device.platform.platform_base import PlatformBase, serial_to_id
from module.exception import RequestHumanTakeover


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
        mumu_vms_config=lambda _: "",
    )


def _make_platform(
    *,
    instances: list[object],
    serial: str = "127.0.0.1:16384",
    running: list[str] | None = None,
):
    session = SimpleNamespace(
        serial=serial,
        is_mumu_family=True,
        is_mumu12_family=True,
    )
    platform = PlatformBase(session)
    manager = SimpleNamespace(
        all_emulator_instances=instances,
        running=running or [],
        running_calls=0,
    )

    def iter_running_emulator():
        manager.running_calls += 1
        return iter(manager.running)

    manager.iter_running_emulator = iter_running_emulator
    vars(platform)["emulator_manager"] = manager
    return platform


def _make_keep_alive_platform(
    *, app_keep_alive: str, player_version: str = "3.8.27.2950", instances: list[object] | None = None
):
    platform = _make_platform(instances=instances or [])
    props = {
        "nemud.app_keep_alive": app_keep_alive,
        "nemud.player_version": player_version,
    }

    def adb_getprop(name: str) -> str:
        return props[name]

    platform.session.adb_getprop = adb_getprop
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
    assert platform.emulator_manager.running_calls == 0


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


def test_check_mumu_bridge_network_allows_disabled_bridge(tmp_path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"network_bridge_opened": False}}), encoding="utf-8")
    instance = _instance()
    instance.mumu_vms_config = lambda _: config_file.as_posix()
    platform = _make_platform(
        instances=[
            instance,
        ],
    )

    assert platform.check_mumu_bridge_network()


def test_check_mumu_bridge_network_rejects_enabled_bridge(tmp_path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"network_bridge_opened": True}}), encoding="utf-8")
    instance = _instance()
    instance.mumu_vms_config = lambda _: config_file.as_posix()
    platform = _make_platform(
        instances=[
            instance,
        ],
    )

    with pytest.raises(RequestHumanTakeover):
        platform.check_mumu_bridge_network()


def test_check_mumu_app_keep_alive_accepts_disabled_getprop() -> None:
    platform = _make_keep_alive_platform(app_keep_alive="false")

    assert platform.check_mumu_app_keep_alive()


def test_check_mumu_app_keep_alive_rejects_enabled_getprop() -> None:
    platform = _make_keep_alive_platform(app_keep_alive="true")

    with pytest.raises(RequestHumanTakeover):
        platform.check_mumu_app_keep_alive()


def test_is_mumu_over_version_400_uses_empty_player_version() -> None:
    platform = _make_keep_alive_platform(app_keep_alive="", player_version="")

    assert platform.is_mumu_over_version_400


def test_check_mumu_app_keep_alive_400_accepts_disabled_config(tmp_path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"app_keptlive": False}}), encoding="utf-8")
    instance = _instance()
    instance.mumu_vms_config = lambda _: config_file.as_posix()
    platform = _make_keep_alive_platform(app_keep_alive="", player_version="", instances=[instance])

    assert platform.check_mumu_app_keep_alive()


def test_check_mumu_app_keep_alive_400_rejects_enabled_config(tmp_path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"app_keptlive": True}}), encoding="utf-8")
    instance = _instance()
    instance.mumu_vms_config = lambda _: config_file.as_posix()
    platform = _make_keep_alive_platform(app_keep_alive="", player_version="", instances=[instance])

    with pytest.raises(RequestHumanTakeover):
        platform.check_mumu_app_keep_alive()
