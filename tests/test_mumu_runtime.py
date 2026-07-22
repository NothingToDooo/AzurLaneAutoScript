import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, overload

import pytest
from adbutils import AdbClient

from module.device.mumu_instance import MuMuInstance
from module.device.runtime import MumuRuntime
from module.exception import HumanTakeoverRequiredError
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from pathlib import Path

    from adbutils import AdbConnection

    from module.device.contracts import AdbCommand
    from module.device.control_options import Duration


@dataclass(slots=True)
class _Config:
    Emulator_Serial: str
    Emulator_MuMuPath: str
    MINITOUCH_FILEPATH_REMOTE: str = "/data/local/tmp/minitouch"


class _Session:
    def __init__(
        self,
        serial: str,
        *,
        configured_serial: str | None = None,
        mumu_path: str = "C:/MuMu/nx_main/MuMuNxMain.exe",
    ) -> None:
        self.serial = serial
        self.config = _Config(Emulator_Serial=configured_serial or serial, Emulator_MuMuPath=mumu_path)
        self.is_mumu_family = True
        self.is_mumu12_family = True
        self.package = "com.bilibili.azurlane"
        self.adb_client = AdbClient()
        self.orientation = 0
        self.props: dict[str, str] = {}
        self.recovery_calls = 0
        self.shell_calls = 0

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

    @staticmethod
    def adb_forward(remote: str) -> int:
        del remote
        return 0

    @staticmethod
    def adb_forward_remove(local: str) -> None:
        del local

    def get_orientation(self) -> int:
        return self.orientation

    @staticmethod
    def sleep(second: Duration, /) -> None:
        del second

    @staticmethod
    def list_device() -> SelectedGrids:
        return SelectedGrids([])

    def list_known_packages(self, *, show_log: bool = True) -> list[str]:
        del show_log
        return [self.package]


def _instance(tmp_path: Path, *, instance_id: int = 0, name: str = "MuMuPlayer-15.0-0") -> MuMuInstance:
    executable = tmp_path / "MuMu Player 12" / "nx_main" / "MuMuNxMain.exe"
    return MuMuInstance(
        executable=executable,
        instance_id=instance_id,
        name=name,
        config_dir=tmp_path / "MuMu Player 12" / "vms" / name / "configs",
    )


def _make_runtime(
    *,
    serial: str = "127.0.0.1:16384",
    app_keep_alive: str = "",
    player_version: str = "3.8.27.2950",
    instance: MuMuInstance | None = None,
) -> MumuRuntime:
    session = _Session(serial)
    session.props = {
        "nemud.app_keep_alive": app_keep_alive,
        "nemud.player_version": player_version,
    }
    runtime = MumuRuntime(session)
    if instance is not None:
        runtime.__dict__["emulator_instance"] = instance
    return runtime


def test_emulator_instance_uses_configured_serial_identity_after_live_port_shift(tmp_path: Path) -> None:
    executable = tmp_path / "MuMu Player 12" / "nx_main" / "MuMuNxMain.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    folder = executable.parent.parent / "vms" / "MuMuPlayer-15.0-1"
    folder.mkdir(parents=True)
    session = _Session(
        "127.0.0.1:16417",
        configured_serial="127.0.0.1:16416",
        mumu_path=executable.as_posix(),
    )
    runtime = MumuRuntime(session)

    instance = runtime.emulator_instance

    assert instance.instance_id == 1
    assert instance.name == folder.name


def test_check_mumu_bridge_network_allows_disabled_bridge(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    instance.config_dir.mkdir(parents=True)
    instance.config_path("customer_config.json").write_text(
        json.dumps({"customer": {"network_bridge_opened": False}}),
        encoding="utf-8",
    )
    runtime = _make_runtime(instance=instance)

    assert runtime.check_mumu_bridge_network()


def test_check_mumu_bridge_network_rejects_enabled_bridge(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    instance.config_dir.mkdir(parents=True)
    instance.config_path("customer_config.json").write_text(
        json.dumps({"customer": {"network_bridge_opened": True}}),
        encoding="utf-8",
    )
    runtime = _make_runtime(instance=instance)

    with pytest.raises(HumanTakeoverRequiredError):
        runtime.check_mumu_bridge_network()


def test_check_mumu_app_keep_alive_accepts_disabled_getprop() -> None:
    runtime = _make_runtime(app_keep_alive="false")

    assert runtime.check_mumu_app_keep_alive()


def test_check_mumu_app_keep_alive_rejects_enabled_getprop() -> None:
    runtime = _make_runtime(app_keep_alive="true")

    with pytest.raises(HumanTakeoverRequiredError):
        runtime.check_mumu_app_keep_alive()


def test_is_mumu_over_version_400_uses_empty_player_version() -> None:
    runtime = _make_runtime(player_version="")

    assert runtime.is_mumu_over_version_400


def test_check_mumu_app_keep_alive_400_accepts_disabled_config(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    instance.config_dir.mkdir(parents=True)
    instance.config_path("customer_config.json").write_text(
        json.dumps({"customer": {"app_keptlive": False}}),
        encoding="utf-8",
    )
    runtime = _make_runtime(player_version="", instance=instance)

    assert runtime.check_mumu_app_keep_alive()


def test_check_mumu_app_keep_alive_400_rejects_enabled_config(tmp_path: Path) -> None:
    instance = _instance(tmp_path)
    instance.config_dir.mkdir(parents=True)
    instance.config_path("customer_config.json").write_text(
        json.dumps({"customer": {"app_keptlive": True}}),
        encoding="utf-8",
    )
    runtime = _make_runtime(player_version="", instance=instance)

    with pytest.raises(HumanTakeoverRequiredError):
        runtime.check_mumu_app_keep_alive()
