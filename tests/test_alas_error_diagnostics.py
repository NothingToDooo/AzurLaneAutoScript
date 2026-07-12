from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import numpy as np

import alas as alas_module
from alas import AzurLaneAutoScript
from module.base.utils import load_image
from module.replay import ClickAction, read_trace
from module.replay.recorder import ReplayRecorder

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from module.config.config import AzurLaneConfig
    from module.device.device import Device


def test_save_error_log_writes_raw_replay_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = ReplayRecorder(max_frames=2)
    image = np.full((8, 12, 3), (11, 22, 33), dtype=np.uint8)
    recorder.record_frame(image)
    recorder.record_action(ClickAction(target="POPUP_CONFIRM_REPLAY"))

    log_file = tmp_path / "alas.log"
    raw_path = r'File "F:\alas\module\sample.py", line 1'
    log_file.write_text(f"before\n{'═' * 20}\n{raw_path}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(alas_module, "get_log_file", lambda: str(log_file))

    runner = object.__new__(AzurLaneAutoScript)
    vars(runner)["config"] = cast("AzurLaneConfig", SimpleNamespace(Error_SaveError=True))
    vars(runner)["device"] = cast("Device", SimpleNamespace(replay_recorder=recorder))

    runner.save_error_log()

    error_folders = list((tmp_path / "log" / "error").iterdir())
    assert len(error_folders) == 1
    error_folder = error_folders[0]
    frames = read_trace(error_folder / "trace.json")
    assert frames[0].expected_actions == (ClickAction(target="POPUP_CONFIRM_REPLAY"),)
    assert load_image(frames[0].image_path)[0, 0].tolist() == [11, 22, 33]
    assert raw_path in (error_folder / "log.txt").read_text(encoding="utf-8")
