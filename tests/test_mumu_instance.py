from typing import TYPE_CHECKING

import pytest

from module.device.mumu_instance import (
    MuMuInstance,
    MuMuInstanceResolutionError,
    resolve_mumu_instance,
)

if TYPE_CHECKING:
    from pathlib import Path


def _installation(tmp_path: Path) -> tuple[Path, Path]:
    executable = tmp_path / "MuMu Player 12" / "nx_main" / "MuMuNxMain.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    vms = executable.parent.parent / "vms"
    vms.mkdir()
    return executable, vms


def test_resolve_mumu_instance_uses_configured_path_and_serial_instance_id_while_stopped(tmp_path: Path) -> None:
    executable, vms = _installation(tmp_path)
    expected_folder = vms / "MuMuPlayer-15.0-1"
    expected_folder.mkdir()
    (vms / "MuMuPlayer-15.0-0").mkdir()

    instance = resolve_mumu_instance(executable.as_posix(), "127.0.0.1:16416")

    assert instance == MuMuInstance(
        executable=executable.resolve(),
        instance_id=1,
        name="MuMuPlayer-15.0-1",
        config_dir=expected_folder / "configs",
    )
    assert instance.manager_executable == executable.with_name("MuMuManager.exe").resolve()
    assert instance.config_path("customer_config.json") == expected_folder / "configs" / "customer_config.json"


def test_resolve_mumu_instance_rejects_missing_configured_executable(tmp_path: Path) -> None:
    executable = tmp_path / "MuMu Player 12" / "nx_main" / "MuMuNxMain.exe"

    with pytest.raises(MuMuInstanceResolutionError, match="MuMu executable does not exist"):
        resolve_mumu_instance(executable.as_posix(), "127.0.0.1:16384")


def test_resolve_mumu_instance_rejects_wrong_configured_executable(tmp_path: Path) -> None:
    executable = tmp_path / "MuMu Player 12" / "shell" / "MuMuPlayer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    with pytest.raises(MuMuInstanceResolutionError, match=r"must be named MuMuNxMain\.exe"):
        resolve_mumu_instance(executable.as_posix(), "127.0.0.1:16384")


def test_resolve_mumu_instance_rejects_missing_vms_directory(tmp_path: Path) -> None:
    executable = tmp_path / "MuMu Player 12" / "nx_main" / "MuMuNxMain.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    with pytest.raises(MuMuInstanceResolutionError, match="MuMu vms directory does not exist"):
        resolve_mumu_instance(executable.as_posix(), "127.0.0.1:16384")


def test_resolve_mumu_instance_reports_observed_names_when_id_is_missing(tmp_path: Path) -> None:
    executable, vms = _installation(tmp_path)
    (vms / "MuMuPlayer-15.0-0").mkdir()
    (vms / "notes").mkdir()

    with pytest.raises(MuMuInstanceResolutionError) as exc_info:
        resolve_mumu_instance(executable.as_posix(), "127.0.0.1:16416")

    message = str(exc_info.value)
    assert "MuMu instance id 1 was not found" in message
    assert "observed names: MuMuPlayer-15.0-0, notes" in message


def test_resolve_mumu_instance_rejects_duplicate_instance_id_with_observed_names(tmp_path: Path) -> None:
    executable, vms = _installation(tmp_path)
    (vms / "MuMuPlayer-12.0-1").mkdir()
    (vms / "MuMuPlayer-15.0-1").mkdir()

    with pytest.raises(MuMuInstanceResolutionError) as exc_info:
        resolve_mumu_instance(executable.as_posix(), "127.0.0.1:16416")

    message = str(exc_info.value)
    assert "MuMu instance id 1 is ambiguous" in message
    assert "observed names: MuMuPlayer-12.0-1, MuMuPlayer-15.0-1" in message
