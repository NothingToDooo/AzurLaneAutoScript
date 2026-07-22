from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import numpy as np

from module.combat_ui import assets as combat_ui_assets
from module.exercise import assets as exercise_assets
from module.exercise.hp_daemon import HpDaemon

if TYPE_CHECKING:
    import pytest

    from module.base.timer import Timer
    from module.base.type_alias import Area, ImageArray
    from module.config.config import AzurLaneConfig


def test_nier_pause_uses_new_exercise_hp_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = object.__new__(HpDaemon)
    daemon.config = cast("AzurLaneConfig", SimpleNamespace(Exercise_LowHpThreshold=0.3))
    resets: list[bool] = []
    daemon.low_hp_confirm_timer = cast("Timer", SimpleNamespace(reset=lambda: resets.append(True)))
    areas: list[Area] = []

    def calculate_hp(_image: object, *, area: Area, **_kwargs: object) -> float:
        areas.append(area)
        return 1.0

    monkeypatch.setattr(HpDaemon, "_calculate_exercise_hp", staticmethod(calculate_hp))
    image = cast("ImageArray", np.zeros((1, 1, 3), dtype=np.uint8))

    assert (
        daemon._at_low_hp(  # ruff:ignore[private-member-access] - 直接验证 Nier 皮肤走新版演习血条布局。
            image, pause=combat_ui_assets.PAUSE_Nier
        )
        is False
    )
    assert areas == [exercise_assets.ATTACKER_HP_AREA_New.area, exercise_assets.DEFENDER_HP_AREA_New.area]
    assert resets == [True]
