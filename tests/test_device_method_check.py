from types import SimpleNamespace

import pytest

from module.device.device import Device
from module.exception import RequestHumanTakeover


def _device_context(
    *,
    emulator_type: str | None = "MuMuPlayer12",
) -> Device:
    device = object.__new__(Device)
    device.config = SimpleNamespace()
    vars(device)["_runtime"] = SimpleNamespace(mumu_runtime=SimpleNamespace())
    device.emulator_instance = None if emulator_type is None else SimpleNamespace(type=emulator_type)
    return device


def test_method_check_accepts_mumu12_instance_regardless_of_serial_shape() -> None:
    device = _device_context(emulator_type="MuMuPlayer12")

    device.method_check()


@pytest.mark.parametrize("emulator_type", [None, "", "MuMuPlayer", "MuMuPlayerX"])
def test_method_check_rejects_non_mumu12_instances(emulator_type: str | None) -> None:
    device = _device_context(emulator_type=emulator_type)

    with pytest.raises(RequestHumanTakeover):
        device.method_check()
