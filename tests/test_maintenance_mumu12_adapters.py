from typing import TYPE_CHECKING

import pytest
from config_factory import in_memory_config

import module.adapters.maintenance_mumu12 as maintenance_adapters
from module.adapters.maintenance_mumu12 import LocalUncensoredAssetBuilder, Mumu12DeviceAppLifecycle
from module.application import AbortRequested, AbortToken
from module.device.device import Device
from module.maintenance import UncensoredPayload

if TYPE_CHECKING:
    from pathlib import Path


class _AppController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")


class _Device(Device):
    def __init__(self, app: _AppController) -> None:
        self.app = app
        self.local_calls: list[str] = []

    @property
    def app_controller(self) -> _AppController:
        return self.app

    def stuck_record_clear(self) -> None:
        self.local_calls.append("stuck-clear")

    def click_record_clear(self) -> None:
        self.local_calls.append("click-clear")


def test_uncensored_builder_replaces_stale_payload_with_exact_localization_file(tmp_path: Path) -> None:
    output = tmp_path / "toolkit" / "files"
    output.mkdir(parents=True)
    (output / "stale.txt").write_text("stale", encoding="utf-8")

    payload = LocalUncensoredAssetBuilder(tmp_path / "toolkit").build(AbortToken())

    assert payload == UncensoredPayload(output.resolve())
    assert sorted(path.name for path in output.iterdir()) == ["localization.txt"]
    assert (output / "localization.txt").read_text(encoding="utf-8") == (
        "Localization = true\nLocalization_skin = true\n"
    )


def test_uncensored_builder_checks_cancellation_before_touching_files(tmp_path: Path) -> None:
    output = tmp_path / "toolkit" / "files"
    output.mkdir(parents=True)
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    abort = AbortToken()
    abort.request("manual stop")

    with pytest.raises(AbortRequested, match="manual stop"):
        LocalUncensoredAssetBuilder(tmp_path / "toolkit").build(abort)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_device_lifecycle_uses_the_real_app_service_and_clears_local_records() -> None:
    app = _AppController()
    device = _Device(app)
    lifecycle = Mumu12DeviceAppLifecycle(device)

    lifecycle.start(AbortToken())
    lifecycle.stop(AbortToken())

    assert app.calls == ["start", "stop"]
    assert device.local_calls == ["stuck-clear", "click-clear", "stuck-clear", "click-clear"]


def test_device_lifecycle_checks_cancellation_before_app_service_io() -> None:
    app = _AppController()
    lifecycle = Mumu12DeviceAppLifecycle(_Device(app))
    abort = AbortToken()
    abort.request("manual stop")

    with pytest.raises(AbortRequested, match="manual stop"):
        lifecycle.start(abort)

    assert app.calls == []


def test_maintenance_activation_clears_the_previous_task_runtime_overlay() -> None:
    config = in_memory_config("test", {}, task="Main")
    config.replace_runtime_overlay(
        MAP_CHAPTER_SWITCH_20241219=True,
        Campaign_Mode="hard",
    )
    device = _Device(_AppController())

    maintenance_adapters._activate(config, device, "Benchmark", AbortToken())  # noqa: SLF001

    assert vars(config)["_runtime_overlay"] == {}
    assert getattr(config, "MAP_CHAPTER_SWITCH_20241219", None) is not True
    assert getattr(config, "Campaign_Mode", None) != "hard"
