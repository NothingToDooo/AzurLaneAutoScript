from types import SimpleNamespace

import pytest

from module.campaign import run as campaign_run_module
from module.campaign.run import CampaignRun
from module.content import LoadedCampaignModule, LoadedStage, StageRef
from module.exception import RequestHumanTakeover
from module.hard import hard as hard_module
from module.hard.hard import CampaignHard
from module.map.map_base import CampaignMap

AFTER_RUN_METHOD = "_handle_campaign_after_run"
ENSURE_UI_METHOD = "_ensure_campaign_run_ui"


class _TaskStopped(Exception):
    pass


class _LoadedConfig:
    pass


class _RunnerConfig:
    def __init__(self) -> None:
        self.merged: list[object] = []

    def merge(self, config: object):
        self.merged.append(config)
        return self


class _LoadedCampaign:
    def __init__(self, *, config: _RunnerConfig, device: object) -> None:
        self.config = config
        self.device = device


class _StageAdapter:
    def __init__(self, loaded_stage: LoadedStage) -> None:
        self.loaded_stage = loaded_stage
        self.stage_refs: list[StageRef] = []
        self.helper_refs: list[StageRef] = []

    def load(self, ref: StageRef) -> LoadedStage:
        self.stage_refs.append(ref)
        return self.loaded_stage

    def load_campaign_helper(self, ref: StageRef) -> LoadedCampaignModule:
        self.helper_refs.append(ref)
        return LoadedCampaignModule(_LoadedConfig, _LoadedCampaign)


class _MissingStageAdapter(_StageAdapter):
    def load(self, ref: StageRef) -> LoadedStage:
        module_name = f"campaign.{ref.pack_id}.{ref.stage_id}"
        raise ModuleNotFoundError(module_name)


def _make_load_runner() -> tuple[CampaignRun, _StageAdapter]:
    runner = object.__new__(CampaignRun)
    runner.config = _RunnerConfig()
    runner.device = object()
    loaded = LoadedStage(_LoadedConfig, _LoadedCampaign, CampaignMap("TEST"))
    adapter = _StageAdapter(loaded)
    runner.stage_adapter = adapter
    return runner, adapter


class _HardConfig:
    Hard_HardStage = "7-2"
    Hard_HardFleet = 1

    def __init__(self) -> None:
        self.overrides: list[dict[str, object]] = []
        self.delays: list[dict[str, object]] = []
        self.task_calls: list[str] = []

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)

    def task_delay(self, **kwargs: object) -> None:
        self.delays.append(kwargs)

    def task_call(self, task: str) -> None:
        self.task_calls.append(task)


class _HardDevice:
    def __init__(self) -> None:
        self.image = "hard-screen"
        self.screenshot_calls = 0

    def screenshot(self) -> None:
        self.screenshot_calls += 1


class _HardCampaign:
    def __init__(self) -> None:
        self.device = SimpleNamespace(image=None)
        self.MAP = None
        self.ensure_ui_calls: list[tuple[str, str]] = []
        self.auto_search_exit_calls = 0

    def ensure_campaign_ui(self, *, name: str, mode: str) -> None:
        self.ensure_ui_calls.append((name, mode))

    def run(self) -> None:
        pytest.fail("OCR 剩余次数为 0 时不应运行战役")

    def ensure_auto_search_exit(self) -> None:
        self.auto_search_exit_calls += 1


class _AfterRunConfig:
    def __init__(self) -> None:
        self.StopCondition_RunCount = 0
        self.is_task_switched = False
        self.task_stop_calls = 0

    def task_switched(self) -> bool:
        return self.is_task_switched

    def task_stop(self) -> None:
        self.task_stop_calls += 1
        raise _TaskStopped


class _AfterRunCampaign:
    def __init__(self) -> None:
        self.config = SimpleNamespace(MAP_IS_ONE_TIME_STAGE=False)
        self.map_stop_calls = 0
        self.auto_search_exit_calls = 0

    def handle_map_stop(self) -> None:
        self.map_stop_calls += 1

    def ensure_auto_search_exit(self) -> None:
        self.auto_search_exit_calls += 1


class _RunDevice:
    def __init__(self) -> None:
        self.has_cached_image = True
        self.image = "cached"
        self.stuck_clear_calls = 0
        self.click_clear_calls = 0
        self.screenshot_calls = 0

    def stuck_record_clear(self) -> None:
        self.stuck_clear_calls += 1

    def click_record_clear(self) -> None:
        self.click_clear_calls += 1

    def screenshot(self) -> None:
        self.screenshot_calls += 1
        self.has_cached_image = True
        self.image = "fresh"


class _RunCampaign:
    def __init__(self) -> None:
        self.device = SimpleNamespace(image=None)
        self.in_map = False
        self.in_auto_search_menu = False
        self.withdraw_calls = 0
        self.ensure_calls: list[tuple[str, str]] = []

    def is_in_map(self) -> bool:
        return self.in_map

    def is_in_auto_search_menu(self) -> bool:
        return self.in_auto_search_menu

    def withdraw(self) -> None:
        self.withdraw_calls += 1

    def ensure_campaign_ui(self, *, name: str, mode: str) -> None:
        self.ensure_calls.append((name, mode))


def _make_runner(*, stop_triggered: bool = False):
    runner = object.__new__(CampaignRun)
    runner.config = _AfterRunConfig()
    runner.campaign = _AfterRunCampaign()
    runner.run_count = 0
    runner.is_stage_loop = False
    runner.stop_oil_checks = []

    def triggered_stop_condition(*, oil_check: bool = True) -> bool:
        runner.stop_oil_checks.append(oil_check)
        return stop_triggered

    runner.triggered_stop_condition = triggered_stop_condition
    return runner


def _make_ui_runner(*, auto_search_continue: bool = False):
    runner = object.__new__(CampaignRun)
    runner.device = _RunDevice()
    runner.campaign = _RunCampaign()
    runner.stage = "d3"
    runner.disable_raid_calls = 0
    runner.commission_notice_calls = 0

    def can_use_auto_search_continue() -> bool:
        return auto_search_continue

    def disable_raid_on_event() -> None:
        runner.disable_raid_calls += 1

    def handle_commission_notice() -> None:
        runner.commission_notice_calls += 1

    runner.can_use_auto_search_continue = can_use_auto_search_continue
    runner.disable_raid_on_event = disable_raid_on_event
    runner.handle_commission_notice = handle_commission_notice
    return runner


def _handle_after_run(runner) -> bool:
    return getattr(runner, AFTER_RUN_METHOD)()


def _ensure_run_ui(runner, mode: str = "normal") -> None:
    getattr(runner, ENSURE_UI_METHOD)(mode)


def test_load_campaign_uses_stage_adapter_and_preserves_construction_semantics() -> None:
    runner, adapter = _make_load_runner()

    assert runner.load_campaign("t1", folder="event_20260625_cn") is True

    assert adapter.stage_refs == [StageRef("event_20260625_cn", "t1")]
    assert runner.loaded_stage is adapter.loaded_stage
    assert runner.name == "t1"
    assert runner.folder == "event_20260625_cn"
    assert runner.stage == "t1"
    assert isinstance(runner.campaign, _LoadedCampaign)
    assert runner.campaign.device is runner.device
    assert runner.campaign.config is not runner.config
    assert len(runner.campaign.config.merged) == 1
    assert isinstance(runner.campaign.config.merged[0], _LoadedConfig)


def test_load_campaign_keeps_existing_same_name_shortcut() -> None:
    runner, adapter = _make_load_runner()

    assert runner.load_campaign("campaign_7_2", folder="campaign_main") is True
    assert runner.stage == "7-2"
    assert runner.load_campaign("campaign_7_2", folder="another_folder") is False
    assert adapter.stage_refs == [StageRef("campaign_main", "campaign_7_2")]
    assert runner.folder == "campaign_main"


def test_load_campaign_helper_uses_explicit_non_stage_contract() -> None:
    runner, adapter = _make_load_runner()

    assert runner.load_campaign_helper("campaign_hard", folder="campaign_hard") is True

    assert adapter.stage_refs == []
    assert adapter.helper_refs == [StageRef("campaign_hard", "campaign_hard")]
    assert runner.loaded_stage is None
    assert isinstance(runner.campaign, _LoadedCampaign)
    assert runner.stage == "hard"


def test_load_campaign_preserves_missing_module_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, adapter = _make_load_runner()
    warnings: list[str] = []
    criticals: list[str] = []
    monkeypatch.setattr(runner, "stage_adapter", _MissingStageAdapter(adapter.loaded_stage))
    monkeypatch.setattr(campaign_run_module.logger, "warning", warnings.append)
    monkeypatch.setattr(campaign_run_module.logger, "critical", criticals.append)

    with pytest.raises(RequestHumanTakeover) as exc_info:
        runner.load_campaign("t1", folder="event_missing")

    assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)
    assert warnings == [
        "Map file not found: campaign.event_missing.t1",
        "Folder not exists: ./campaign/event_missing",
    ]
    assert criticals == [
        "Possible reason #1: This event (event_missing) does not have t1",
        (
            "Possible reason #2: You are using an old Alas, please check for update, "
            "or make map files yourself using dev_tools/map_extractor.py"
        ),
    ]


def test_campaign_hard_loads_behavior_through_helper_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(CampaignHard)
    runner.config = _HardConfig()
    runner.device = _HardDevice()
    helper_calls: list[tuple[str, str]] = []

    def unexpected_stage_load(name: str, folder: str = "campaign_main") -> bool:
        pytest.fail(f"hard helper 不应作为 stage 装载：{folder}.{name}")

    def load_helper(name: str, folder: str = "campaign_main") -> bool:
        helper_calls.append((name, folder))
        runner.campaign = _HardCampaign()
        return True

    runner.load_campaign = unexpected_stage_load
    runner.load_campaign_helper = load_helper
    selected_map = object()
    monkeypatch.setattr(
        hard_module.importlib,
        "import_module",
        lambda _name, _package: SimpleNamespace(MAP=selected_map),
    )
    monkeypatch.setattr(hard_module.OCR_HARD_REMAIN, "ocr", lambda _image: 0)

    runner.run()

    assert helper_calls == [("campaign_hard", "campaign_hard")]
    assert runner.campaign.MAP is selected_map
    assert runner.device.screenshot_calls == 1
    assert runner.campaign.device.image == "hard-screen"
    assert runner.campaign.ensure_ui_calls == [("7-2", "hard")]
    assert runner.campaign.auto_search_exit_calls == 1
    assert runner.config.delays == [{"server_update": True}]
    assert runner.config.task_calls == ["Reward"]


def test_after_run_updates_run_count() -> None:
    runner = _make_runner()
    runner.config.StopCondition_RunCount = 2

    assert not _handle_after_run(runner)
    assert runner.run_count == 1
    assert runner.config.StopCondition_RunCount == 1


def test_after_run_stops_when_stop_condition_triggers() -> None:
    runner = _make_runner(stop_triggered=True)
    runner.config.StopCondition_RunCount = 2

    assert _handle_after_run(runner)
    assert runner.run_count == 1
    assert runner.config.StopCondition_RunCount == 1


def test_after_run_stops_on_one_time_stage() -> None:
    runner = _make_runner()
    runner.campaign.config.MAP_IS_ONE_TIME_STAGE = True

    assert _handle_after_run(runner)
    assert runner.campaign.map_stop_calls == 1


def test_after_run_stops_on_stage_loop() -> None:
    runner = _make_runner()
    runner.is_stage_loop = True

    assert _handle_after_run(runner)


def test_after_run_stops_on_scheduler_switch() -> None:
    runner = _make_runner()
    runner.config.is_task_switched = True

    with pytest.raises(_TaskStopped):
        _handle_after_run(runner)

    assert runner.campaign.auto_search_exit_calls == 1
    assert runner.config.task_stop_calls == 1


def test_ensure_run_ui_takes_fresh_screenshot_when_needed() -> None:
    runner = _make_ui_runner()
    runner.device.has_cached_image = False

    _ensure_run_ui(runner, mode="hard")

    assert runner.device.stuck_clear_calls == 1
    assert runner.device.click_clear_calls == 1
    assert runner.device.screenshot_calls == 1
    assert runner.campaign.device.image == "fresh"
    assert runner.campaign.ensure_calls == [("d3", "hard")]
    assert runner.disable_raid_calls == 1
    assert runner.commission_notice_calls == 1


def test_ensure_run_ui_retreats_when_already_in_map() -> None:
    runner = _make_ui_runner()
    runner.campaign.in_map = True

    _ensure_run_ui(runner)

    assert runner.campaign.withdraw_calls == 1
    assert runner.campaign.ensure_calls == [("d3", "normal")]


def test_ensure_run_ui_keeps_usable_auto_search_menu() -> None:
    runner = _make_ui_runner(auto_search_continue=True)
    runner.campaign.in_auto_search_menu = True

    _ensure_run_ui(runner)

    assert runner.campaign.ensure_calls == []


def test_ensure_run_ui_closes_unusable_auto_search_menu() -> None:
    runner = _make_ui_runner(auto_search_continue=False)
    runner.campaign.in_auto_search_menu = True

    _ensure_run_ui(runner)

    assert runner.campaign.ensure_calls == [("d3", "normal")]
