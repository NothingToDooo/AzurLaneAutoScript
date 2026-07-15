from datetime import time
from typing import cast

import pytest

from module.adapters.facility_mumu12 import (
    project_commission_settings,
    project_research_settings,
    project_tactical_settings,
)
from module.application import DailySchedule, DelayRange
from module.gameplay.facility import (
    CommissionPreset,
    CommissionSelectionPolicy,
    CommissionSettings,
    ResearchResourcePolicy,
    ResearchSelectionPolicy,
    ResearchSettings,
    TacticalExperienceOverflowPolicy,
    TacticalRapidTrainingSlot,
    TacticalSettings,
    TacticalStudentPolicy,
)

_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(4), time(12)))


def test_research_projection_contains_every_ui_decision_field() -> None:
    settings = ResearchSettings(
        _SCHEDULE,
        ResearchSelectionPolicy(
            use_cube=ResearchResourcePolicy.ONLY_HALF_HOUR,
            use_coin=ResearchResourcePolicy.ALWAYS_USE,
            use_part=ResearchResourcePolicy.DO_NOT_USE,
            allow_delay=True,
            preset_filter="series_9_blueprint_only",
            custom_filter="Q > G > shortest",
        ),
    )

    assert dict(project_research_settings(settings)) == {
        "Research_UseCube": "only_05_hour",
        "Research_UseCoin": "always_use",
        "Research_UsePart": "do_not_use",
        "Research_AllowDelay": True,
        "Research_PresetFilter": "series_9_blueprint_only",
        "Research_CustomFilter": "Q > G > shortest",
    }


def test_commission_projection_contains_every_selection_field_but_no_scheduler_control() -> None:
    settings = CommissionSettings(
        DelayRange(1_800, 1_800),
        commission_limit_enabled=True,
        selection=CommissionSelectionPolicy(
            preset_filter=CommissionPreset.CUSTOM,
            custom_filter="DailyEvent > Gem-8 > shortest",
            do_major_commission=True,
        ),
    )

    fields = dict(project_commission_settings(settings))

    assert fields == {
        "Commission_PresetFilter": "custom",
        "Commission_CustomFilter": "DailyEvent > Gem-8 > shortest",
        "Commission_DoMajorCommission": True,
    }
    assert all("Scheduler" not in field_name for field_name in fields)


def test_tactical_projection_contains_book_overflow_and_student_policy() -> None:
    settings = TacticalSettings(
        DelayRange(1_200, 1_200),
        _SCHEDULE,
        "SameT4 > BlueT3 > first",
        TacticalRapidTrainingSlot.SLOT_2,
        TacticalExperienceOverflowPolicy(
            enabled=False,
            t1_allow=10,
            t2_allow=20,
            t3_allow=30,
            t4_allow=40,
        ),
        TacticalStudentPolicy(enabled=True, favorite=True, minimum_level=70),
    )

    assert dict(project_tactical_settings(settings)) == {
        "Tactical_TacticalFilter": "SameT4 > BlueT3 > first",
        "Tactical_RapidTrainingSlot": "slot_2",
        "ControlExpOverflow_Enable": False,
        "ControlExpOverflow_T1Allow": 10,
        "ControlExpOverflow_T2Allow": 20,
        "ControlExpOverflow_T3Allow": 30,
        "ControlExpOverflow_T4Allow": 40,
        "AddNewStudent_Enable": True,
        "AddNewStudent_Favorite": True,
        "AddNewStudent_MinLevel": 70,
    }


def test_projection_rejects_the_wrong_typed_snapshot() -> None:
    with pytest.raises(TypeError, match="ResearchSettings"):
        project_research_settings(cast("ResearchSettings", object()))
    with pytest.raises(TypeError, match="CommissionSettings"):
        project_commission_settings(cast("CommissionSettings", object()))
    with pytest.raises(TypeError, match="TacticalSettings"):
        project_tactical_settings(cast("TacticalSettings", object()))
