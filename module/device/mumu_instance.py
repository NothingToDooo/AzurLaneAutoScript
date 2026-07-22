import re
from dataclasses import dataclass
from pathlib import Path

from module.device.mumu import MuMuSerial

_MUMU_EXECUTABLE_NAME = "MuMuNxMain.exe"
_MUMU_INSTANCE_NAME = re.compile(r"MuMuPlayer-\d+(?:\.\d+)+-(\d+)")


class MuMuInstanceResolutionError(ValueError):
    """配置的 MuMu 安装无法唯一解析出目标实例。"""


@dataclass(frozen=True, slots=True)
class MuMuInstance:
    executable: Path
    instance_id: int
    name: str
    config_dir: Path

    @property
    def manager_executable(self) -> Path:
        return self.executable.with_name("MuMuManager.exe")

    def config_path(self, filename: str) -> Path:
        return self.config_dir / filename


def _instance_id_from_name(name: str) -> int | None:
    match = _MUMU_INSTANCE_NAME.fullmatch(name)
    return None if match is None else int(match.group(1))


def _observed_names(vms_dir: Path) -> tuple[str, ...]:
    return tuple(sorted(child.name for child in vms_dir.iterdir() if child.is_dir()))


def _format_observed_names(names: tuple[str, ...]) -> str:
    return ", ".join(names) if names else "<none>"


def resolve_mumu_instance(executable_path: str, serial: str) -> MuMuInstance:
    """从唯一配置路径和 serial 实例 ID 解析 MuMu 实例。"""

    parsed_serial = MuMuSerial.parse(serial)
    if parsed_serial is None:
        message = f"invalid MuMu12 serial: {serial!r}"
        raise MuMuInstanceResolutionError(message)

    executable = Path(executable_path)
    if not executable.is_absolute():
        message = f"MuMu executable path must be absolute: {executable}"
        raise MuMuInstanceResolutionError(message)
    if not executable.is_file():
        message = f"MuMu executable does not exist: {executable}"
        raise MuMuInstanceResolutionError(message)
    if executable.name.casefold() != _MUMU_EXECUTABLE_NAME.casefold():
        message = f"MuMu executable must be named {_MUMU_EXECUTABLE_NAME}: {executable}"
        raise MuMuInstanceResolutionError(message)

    executable = executable.resolve()
    vms_dir = executable.parent.parent / "vms"
    if not vms_dir.is_dir():
        message = f"MuMu vms directory does not exist: {vms_dir}"
        raise MuMuInstanceResolutionError(message)

    observed_names = _observed_names(vms_dir)
    matches = tuple(name for name in observed_names if _instance_id_from_name(name) == parsed_serial.instance_id)
    observed = _format_observed_names(observed_names)
    if not matches:
        message = (
            f"MuMu instance id {parsed_serial.instance_id} was not found under {vms_dir}; observed names: {observed}"
        )
        raise MuMuInstanceResolutionError(message)
    if len(matches) > 1:
        message = (
            f"MuMu instance id {parsed_serial.instance_id} is ambiguous under {vms_dir}; observed names: {observed}"
        )
        raise MuMuInstanceResolutionError(message)

    name = matches[0]
    return MuMuInstance(
        executable=executable,
        instance_id=parsed_serial.instance_id,
        name=name,
        config_dir=vms_dir / name / "configs",
    )
