import json
from typing import TYPE_CHECKING, ClassVar, Literal, overload, override

import pytest
from adbutils import AdbClient

from module.device.mumu_runtime_base import MumuRuntimeBase, serial_to_id
from module.device.platform.emulator_base import EmulatorInstanceBase, EmulatorManagerBase
from module.exception import HumanTakeoverRequiredError
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from adbutils import AdbConnection

    from module.device.contracts import AdbCommand


class _Session:
    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.is_mumu_family = True
        self.is_mumu12_family = True
        self.package = "com.bilibili.azurlane"
        self.adb_client = AdbClient()
        self.props: dict[str, str] = {}
        self.recovery_calls = 0
        self.shell_calls = 0
        self.list_device_calls = 0

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[False] = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[True] = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> bytes: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[False],
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> AdbConnection: ...

    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: bool = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str | bytes | AdbConnection:
        del cmd, recvall, timeout, rstrip
        self.shell_calls += 1
        if stream:
            raise AssertionError
        return ""

    def adb_start_server(self) -> int:
        self.recovery_calls += 1
        return 0

    def adb_reconnect(self) -> None:
        self.recovery_calls += 1

    def detect_package(self) -> None:
        self.recovery_calls += 1

    def adb_getprop(self, name: str) -> str:
        return self.props[name]

    def list_device(self) -> SelectedGrids[EmulatorInstanceBase]:
        self.list_device_calls += 1
        return SelectedGrids([])

    def list_known_packages(self, *, show_log: bool = True) -> list[str]:
        del show_log
        return [self.package]


class _Instance(EmulatorInstanceBase):
    def __init__(
        self,
        *,
        serial: str,
        name: str,
        path: str,
        emulator_type: str,
        mumu_id: int | None,
    ) -> None:
        super().__init__(serial=serial, name=name, path=path)
        self.emulator_type = emulator_type
        self.mumu_id = mumu_id
        self.config_path = ""

    @property
    @override
    def type(self) -> str:
        return self.emulator_type

    @property
    @override
    def mumu_player_12_id(self) -> int | None:
        return self.mumu_id

    @override
    def mumu_vms_config(self, file: str) -> str:
        del file
        return self.config_path


class _Manager(EmulatorManagerBase):
    _active: ClassVar[_Manager | None] = None

    def __init__(self, instances: list[EmulatorInstanceBase], running: list[str]) -> None:
        self.instances = instances
        self.running = running
        self.running_calls = 0
        _Manager._active = self

    @property
    @override
    def all_emulator_instances(self) -> list[EmulatorInstanceBase]:
        return self.instances

    @staticmethod
    @override
    def iter_running_emulator() -> Iterator[str]:
        manager = _Manager._active
        assert manager is not None
        manager.running_calls += 1
        return iter(manager.running)


class _Runtime(MumuRuntimeBase):
    session: _Session
    emulator_manager: _Manager

    def __init__(self, session: _Session, manager: _Manager) -> None:
        self.emulator_manager = manager
        super().__init__(session)


def _instance(
    *,
    serial: str = "127.0.0.1:16384",
    name: str = "MuMuPlayer-12.0-0",
    path: str = "C:/MuMu/nx_main/MuMuNxMain.exe",
    emulator_type: str = "MuMuPlayer12",
    mumu_id: int | None = None,
) -> _Instance:
    return _Instance(
        serial=serial,
        name=name,
        path=path,
        emulator_type=emulator_type,
        mumu_id=mumu_id,
    )


def _make_runtime(
    *,
    instances: list[EmulatorInstanceBase],
    serial: str = "127.0.0.1:16384",
    running: list[str] | None = None,
) -> _Runtime:
    session = _Session(serial)
    manager = _Manager(instances, running or [])
    return _Runtime(session, manager)


def _make_keep_alive_runtime(
    *,
    app_keep_alive: str,
    player_version: str = "3.8.27.2950",
    instances: list[EmulatorInstanceBase] | None = None,
) -> _Runtime:
    runtime = _make_runtime(instances=instances or [])
    props = {
        "nemud.app_keep_alive": app_keep_alive,
        "nemud.player_version": player_version,
    }

    runtime.session.props = props
    return runtime


def test_serial_to_id_accepts_mumu12_neighbor_ports() -> None:
    assert serial_to_id("127.0.0.1:16384") == 0
    assert serial_to_id("127.0.0.1:16385") == 0
    assert serial_to_id("127.0.0.1:16416") == 1
    assert serial_to_id("emulator-5554") is None
    assert serial_to_id("127.0.0.1:7555") is None


def test_find_emulator_instance_returns_unique_serial_match() -> None:
    expected = _instance(serial="127.0.0.1:16384")
    runtime = _make_runtime(
        instances=[
            expected,
            _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-1"),
        ]
    )

    assert runtime.find_emulator_instance("127.0.0.1:16384") is expected


def test_find_emulator_instance_returns_none_when_serial_missing() -> None:
    runtime = _make_runtime(
        instances=[
            _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-1"),
        ],
        running=["C:/MuMu/nx_main/MuMuNxMain.exe"],
    )

    assert runtime.find_emulator_instance("127.0.0.1:16384") is None
    assert runtime.emulator_manager.running_calls == 0


def test_find_emulator_instance_uses_mumu12_id_to_disambiguate_duplicate_serial() -> None:
    expected = _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-1", mumu_id=1)
    runtime = _make_runtime(
        serial="127.0.0.1:16416",
        instances=[
            _instance(serial="127.0.0.1:16416", name="MuMuPlayer-12.0-0", mumu_id=0),
            expected,
        ],
    )

    assert runtime.find_emulator_instance("127.0.0.1:16416") is expected


def test_emulator_instance_uses_runtime_discovery_without_config_cache() -> None:
    expected = _instance(serial="127.0.0.1:16384")
    runtime = _make_runtime(
        instances=[
            expected,
        ],
    )

    assert runtime.emulator_instance is expected


def test_find_emulator_instance_falls_back_to_single_running_path() -> None:
    expected = _instance(serial="127.0.0.1:16384", name="ArkNights", path="C:/B/MuMuNxMain.exe")
    runtime = _make_runtime(
        instances=[
            _instance(serial="127.0.0.1:16384", name="Default", path="C:/A/MuMuNxMain.exe"),
            expected,
        ],
        running=["C:/B/MuMuNxMain.exe"],
    )

    assert runtime.find_emulator_instance("127.0.0.1:16384") is expected


def test_check_mumu_bridge_network_allows_disabled_bridge(tmp_path: Path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"network_bridge_opened": False}}), encoding="utf-8")
    instance = _instance()
    instance.config_path = config_file.as_posix()
    runtime = _make_runtime(
        instances=[
            instance,
        ],
    )

    assert runtime.check_mumu_bridge_network()


def test_check_mumu_bridge_network_rejects_enabled_bridge(tmp_path: Path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"network_bridge_opened": True}}), encoding="utf-8")
    instance = _instance()
    instance.config_path = config_file.as_posix()
    runtime = _make_runtime(
        instances=[
            instance,
        ],
    )

    with pytest.raises(HumanTakeoverRequiredError):
        runtime.check_mumu_bridge_network()


def test_check_mumu_app_keep_alive_accepts_disabled_getprop() -> None:
    runtime = _make_keep_alive_runtime(app_keep_alive="false")

    assert runtime.check_mumu_app_keep_alive()


def test_check_mumu_app_keep_alive_rejects_enabled_getprop() -> None:
    runtime = _make_keep_alive_runtime(app_keep_alive="true")

    with pytest.raises(HumanTakeoverRequiredError):
        runtime.check_mumu_app_keep_alive()


def test_is_mumu_over_version_400_uses_empty_player_version() -> None:
    runtime = _make_keep_alive_runtime(app_keep_alive="", player_version="")

    assert runtime.is_mumu_over_version_400


def test_check_mumu_app_keep_alive_400_accepts_disabled_config(tmp_path: Path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"app_keptlive": False}}), encoding="utf-8")
    instance = _instance()
    instance.config_path = config_file.as_posix()
    runtime = _make_keep_alive_runtime(app_keep_alive="", player_version="", instances=[instance])

    assert runtime.check_mumu_app_keep_alive()


def test_check_mumu_app_keep_alive_400_rejects_enabled_config(tmp_path: Path) -> None:
    config_file = tmp_path / "customer_config.json"
    config_file.write_text(json.dumps({"customer": {"app_keptlive": True}}), encoding="utf-8")
    instance = _instance()
    instance.config_path = config_file.as_posix()
    runtime = _make_keep_alive_runtime(app_keep_alive="", player_version="", instances=[instance])

    with pytest.raises(HumanTakeoverRequiredError):
        runtime.check_mumu_app_keep_alive()
