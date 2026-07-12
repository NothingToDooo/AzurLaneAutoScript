from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, get_type_hints

import pytest

from module.campaign import run as campaign_run_module
from module.campaign.campaign_base import CampaignBase
from module.campaign.run import CampaignRun
from module.content import LegacyStageContractError, StageRef
from module.content.catalog import ContentCatalog
from module.content.errors import ContentValidationError
from module.content.legacy_stage import LegacyStageModuleAdapter, LoadedCampaignModule, LoadedStage
from module.content.models import EventPack, StageSpec
from module.exception import RequestHumanTakeover
from module.hard import hard as hard_module
from module.hard.hard import CampaignHard
from module.map.map_base import CampaignMap

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

AFTER_RUN_METHOD = "_handle_campaign_after_run"
ENSURE_UI_METHOD = "_ensure_campaign_run_ui"


class _TaskStopped(Exception):
    pass


class _LoadedConfig:
    pass


class _RunnerConfig:
    def __init__(self) -> None:
        self.merged: list[object] = []
        self.merge_hook: Callable[[], None] | None = None

    def merge(self, config: object) -> _RunnerConfig:
        if self.merge_hook is not None:
            self.merge_hook()
        self.merged.append(config)
        return self


class _LoadedCampaign(CampaignBase):
    def __init__(self, *, config: _RunnerConfig, device: object) -> None:
        self.test_config = config
        self.test_device = device
        vars(self)["config"] = config
        vars(self)["device"] = device


class _FailOnceLoadedConfig:
    failures_remaining = 0

    def __init__(self) -> None:
        if self.failures_remaining:
            type(self).failures_remaining -= 1
            message = "config construction failed"
            raise RuntimeError(message)


class _FailOnceLoadedCampaign(_LoadedCampaign):
    failures_remaining = 0

    def __init__(self, *, config: _RunnerConfig, device: object) -> None:
        if self.failures_remaining:
            type(self).failures_remaining -= 1
            message = "campaign construction failed"
            raise RuntimeError(message)
        super().__init__(config=config, device=device)


class _StageAdapter(LegacyStageModuleAdapter):
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


class _NativeStageLoader:
    def __init__(self, loaded_stage: LoadedStage, *, error: Exception | None = None) -> None:
        self.loaded_stage = loaded_stage
        self.error = error
        self.specs: list[StageSpec] = []

    def load(self, spec: StageSpec) -> LoadedStage:
        self.specs.append(spec)
        if self.error is not None:
            raise self.error
        return self.loaded_stage


class _MissingStageAdapter(_StageAdapter):
    def load(self, ref: StageRef) -> LoadedStage:
        self.stage_refs.append(ref)
        module_name = f"campaign.{ref.pack_id}.{ref.stage_id}"
        raise ModuleNotFoundError(module_name)


class _TransactionalAdapter(LegacyStageModuleAdapter):
    def __init__(
        self,
        stage: LoadedStage,
        helper: LoadedCampaignModule,
        *,
        failures_remaining: int = 0,
    ) -> None:
        self.stage = stage
        self.helper = helper
        self.failures_remaining = failures_remaining
        self.stage_refs: list[StageRef] = []
        self.helper_refs: list[StageRef] = []

    def _fail_once(self) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            message = "adapter failed"
            raise LegacyStageContractError(message)

    def load(self, ref: StageRef) -> LoadedStage:
        self.stage_refs.append(ref)
        self._fail_once()
        return self.stage

    def load_campaign_helper(self, ref: StageRef) -> LoadedCampaignModule:
        self.helper_refs.append(ref)
        self._fail_once()
        return self.helper


def _make_load_runner() -> tuple[CampaignRun, _StageAdapter]:
    runner = object.__new__(CampaignRun)
    runner.config = _RunnerConfig()
    runner.device = object()
    loaded = LoadedStage(_LoadedConfig, _LoadedCampaign, CampaignMap("TEST"))
    adapter = _StageAdapter(loaded)
    runner.stage_adapter = adapter
    runner.content_catalog = ContentCatalog()
    return runner, adapter


def _native_catalog(folder: str, name: str) -> tuple[ContentCatalog, StageSpec]:
    spec = StageSpec(StageRef(folder, name), f"stages/{name}.yaml")
    return ContentCatalog((EventPack(pack_id=folder, stages=(spec,)),)), spec


def _load_state(runner: CampaignRun) -> tuple[object, ...]:
    return (
        runner.name,
        runner.folder,
        runner.stage,
        runner.loaded_campaign,
        runner.loaded_stage,
        runner.campaign,
    )


def _assert_load_state_unchanged(runner: CampaignRun, previous: tuple[object, ...]) -> None:
    assert (runner.name, runner.folder, runner.stage) == previous[:3]
    assert runner.loaded_campaign is previous[3]
    assert runner.loaded_stage is previous[4]
    assert runner.campaign is previous[5]


def _merge_failure_once() -> Callable[[], None]:
    failures_remaining = 1

    def fail() -> None:
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            message = "config merge failed"
            raise RuntimeError(message)

    return fail


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

    @staticmethod
    def run() -> None:
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


@dataclass(frozen=True)
class _AfterRunHarness:
    runner: CampaignRun
    config: _AfterRunConfig
    campaign: _AfterRunCampaign


def _make_runner(*, stop_triggered: bool = False) -> _AfterRunHarness:
    runner = object.__new__(CampaignRun)
    config = _AfterRunConfig()
    campaign = _AfterRunCampaign()
    runner.config = config
    runner.campaign = campaign
    runner.run_count = 0
    runner.is_stage_loop = False

    def triggered_stop_condition(*, oil_check: bool = True) -> bool:
        del oil_check
        return stop_triggered

    runner.triggered_stop_condition = triggered_stop_condition
    return _AfterRunHarness(runner, config, campaign)


@dataclass
class _RunHooks:
    disable_raid_calls: int = 0
    commission_notice_calls: int = 0


@dataclass(frozen=True)
class _UiRunHarness:
    runner: CampaignRun
    device: _RunDevice
    campaign: _RunCampaign
    hooks: _RunHooks


def _make_ui_runner(*, auto_search_continue: bool = False) -> _UiRunHarness:
    runner = object.__new__(CampaignRun)
    device = _RunDevice()
    campaign = _RunCampaign()
    hooks = _RunHooks()
    runner.device = device
    runner.campaign = campaign
    runner.stage = "d3"

    def can_use_auto_search_continue() -> bool:
        return auto_search_continue

    def disable_raid_on_event() -> bool:
        hooks.disable_raid_calls += 1
        return False

    def handle_commission_notice() -> None:
        hooks.commission_notice_calls += 1

    runner.can_use_auto_search_continue = can_use_auto_search_continue
    runner.disable_raid_on_event = disable_raid_on_event
    runner.handle_commission_notice = handle_commission_notice
    return _UiRunHarness(runner, device, campaign, hooks)


def _handle_after_run(runner: CampaignRun) -> bool:
    return getattr(runner, AFTER_RUN_METHOD)()


def _ensure_run_ui(runner: CampaignRun, mode: str = "normal") -> None:
    getattr(runner, ENSURE_UI_METHOD)(mode)


def _campaign_load_state_class() -> type[Any]:
    return cast("type[Any]", vars(campaign_run_module)["_CampaignLoadState"])


def test_campaign_load_state_annotations_are_runtime_resolvable() -> None:
    load_state_class = _campaign_load_state_class()

    hints = get_type_hints(load_state_class)

    assert hints["campaign"] is CampaignBase


def test_campaign_load_state_rejects_non_campaign_instance() -> None:
    _, adapter = _make_load_runner()

    with pytest.raises(TypeError, match="CampaignBase"):
        _campaign_load_state_class()(
            name="t1",
            folder="event_test",
            stage="t1",
            loaded=adapter.loaded_stage,
            loaded_stage=adapter.loaded_stage,
            campaign=cast("CampaignBase", object()),
        )


def test_load_campaign_uses_stage_adapter_and_preserves_construction_semantics() -> None:
    runner, adapter = _make_load_runner()

    assert runner.load_campaign("t1", folder="event_20260625_cn") is True

    assert adapter.stage_refs == [StageRef("event_20260625_cn", "t1")]
    assert runner.loaded_stage is adapter.loaded_stage
    assert runner.name == "t1"
    assert runner.folder == "event_20260625_cn"
    assert runner.stage == "t1"
    assert isinstance(runner.campaign, _LoadedCampaign)
    assert runner.campaign.test_device is runner.device
    assert runner.campaign.test_config is not runner.config
    assert len(runner.campaign.test_config.merged) == 1
    assert isinstance(runner.campaign.test_config.merged[0], _LoadedConfig)


def test_load_campaign_prefers_registered_native_stage() -> None:
    runner, adapter = _make_load_runner()
    catalog, spec = _native_catalog("event_native", "t1")
    native_loader = _NativeStageLoader(adapter.loaded_stage)
    runner.content_catalog = catalog
    runner.stage_loader = native_loader

    assert runner.load_campaign("t1", folder="event_native") is True

    assert native_loader.specs == [spec]
    assert adapter.stage_refs == []
    assert runner.loaded_stage is adapter.loaded_stage


def test_registered_native_stage_failure_does_not_fall_back_or_commit() -> None:
    runner, adapter = _make_load_runner()
    assert runner.load_campaign("sp", folder="event_original") is True
    previous_state = _load_state(runner)
    catalog, spec = _native_catalog("event_native", "t1")
    error = ContentValidationError("invalid native stage")
    native_loader = _NativeStageLoader(adapter.loaded_stage, error=error)
    runner.content_catalog = catalog
    runner.stage_loader = native_loader

    with pytest.raises(ContentValidationError, match="invalid native stage"):
        runner.load_campaign("t1", folder="event_native")

    assert native_loader.specs == [spec]
    assert adapter.stage_refs == [StageRef("event_original", "sp")]
    _assert_load_state_unchanged(runner, previous_state)


def test_unregistered_stage_in_known_pack_still_uses_legacy_adapter() -> None:
    runner, adapter = _make_load_runner()
    catalog, _spec = _native_catalog("event_mixed", "t1")
    runner.content_catalog = catalog

    assert runner.load_campaign("sp", folder="event_mixed") is True

    assert adapter.stage_refs == [StageRef("event_mixed", "sp")]


def test_load_campaign_identity_includes_folder_and_name() -> None:
    runner, adapter = _make_load_runner()

    assert runner.load_campaign("sp", folder="event_first") is True
    first_campaign = runner.campaign
    assert runner.load_campaign("sp", folder="event_second") is True
    assert runner.load_campaign("sp", folder="event_second") is False

    assert adapter.stage_refs == [StageRef("event_first", "sp"), StageRef("event_second", "sp")]
    assert runner.folder == "event_second"
    assert runner.stage == "sp"
    assert runner.campaign is not first_campaign


def test_load_campaign_unknown_folder_uses_current_name_as_stage() -> None:
    runner, _ = _make_load_runner()
    assert runner.load_campaign("sp", folder="event_original") is True

    assert runner.load_campaign("custom_stage", folder="custom_pack") is True

    assert (runner.folder, runner.name, runner.stage) == ("custom_pack", "custom_stage", "custom_stage")


@pytest.mark.parametrize("first_kind", ["stage", "helper"])
def test_load_campaign_identity_includes_stage_or_helper_kind(first_kind: str) -> None:
    runner, adapter = _make_load_runner()
    name = "same"
    folder = "event_same"

    if first_kind == "stage":
        assert runner.load_campaign(name, folder=folder) is True
        first_campaign = runner.campaign
        assert runner.load_campaign_helper(name, folder=folder) is True
        assert runner.load_campaign_helper(name, folder=folder) is False
        assert runner.loaded_stage is None
    else:
        assert runner.load_campaign_helper(name, folder=folder) is True
        first_campaign = runner.campaign
        assert runner.load_campaign(name, folder=folder) is True
        assert runner.load_campaign(name, folder=folder) is False
        assert runner.loaded_stage is adapter.loaded_stage

    assert adapter.stage_refs == [StageRef(folder, name)]
    assert adapter.helper_refs == [StageRef(folder, name)]
    assert runner.campaign is not first_campaign


@pytest.mark.parametrize("load_kind", ["stage", "helper"])
@pytest.mark.parametrize("failure_phase", ["adapter", "config", "merge", "campaign"])
def test_campaign_load_builds_locally_then_commits_and_can_retry(
    load_kind: str,
    failure_phase: str,
) -> None:
    runner, _ = _make_load_runner()
    assert runner.load_campaign("sp", folder="event_original") is True
    previous_state = _load_state(runner)

    config_class: type[object] = _LoadedConfig
    campaign_class: type[CampaignBase] = _LoadedCampaign
    failures_remaining = 0
    if failure_phase == "adapter":
        failures_remaining = 1
    elif failure_phase == "config":
        _FailOnceLoadedConfig.failures_remaining = 1
        config_class = _FailOnceLoadedConfig
    elif failure_phase == "merge":
        runner.config.merge_hook = _merge_failure_once()
    elif failure_phase == "campaign":
        _FailOnceLoadedCampaign.failures_remaining = 1
        campaign_class = _FailOnceLoadedCampaign

    stage = LoadedStage(config_class, campaign_class, CampaignMap("RETRY"))
    helper = LoadedCampaignModule(config_class, campaign_class)
    adapter = _TransactionalAdapter(stage, helper, failures_remaining=failures_remaining)
    runner.stage_adapter = adapter

    def load_target() -> bool:
        if load_kind == "stage":
            return runner.load_campaign("sp", folder="event_retry")
        return runner.load_campaign_helper("campaign_hard", folder="campaign_hard")

    expected_error = LegacyStageContractError if failure_phase == "adapter" else RuntimeError
    with pytest.raises(expected_error):
        load_target()

    _assert_load_state_unchanged(runner, previous_state)

    assert load_target() is True
    if load_kind == "stage":
        assert adapter.stage_refs == [StageRef("event_retry", "sp"), StageRef("event_retry", "sp")]
        assert runner.loaded_stage is stage
        assert (runner.folder, runner.name, runner.stage) == ("event_retry", "sp", "sp")
    else:
        assert adapter.helper_refs == [
            StageRef("campaign_hard", "campaign_hard"),
            StageRef("campaign_hard", "campaign_hard"),
        ]
        assert runner.loaded_stage is None
        assert (runner.folder, runner.name, runner.stage) == ("campaign_hard", "campaign_hard", "hard")
    assert runner.loaded_campaign is (stage if load_kind == "stage" else helper)
    assert runner.campaign is not previous_state[5]


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
    assert runner.load_campaign("sp", folder="event_original") is True
    previous_state = _load_state(runner)
    warnings: list[str] = []
    criticals: list[str] = []
    monkeypatch.setattr(runner, "stage_adapter", _MissingStageAdapter(adapter.loaded_stage))
    monkeypatch.setattr(campaign_run_module.logger, "warning", warnings.append)
    monkeypatch.setattr(campaign_run_module.logger, "critical", criticals.append)

    with pytest.raises(RequestHumanTakeover) as exc_info:
        runner.load_campaign("t1", folder="event_missing")

    assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)
    _assert_load_state_unchanged(runner, previous_state)
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
    monkeypatch.setattr(hard_module.OCR_HARD_REMAIN, "ocr_single", lambda _image: 0)

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
    harness = _make_runner()
    harness.config.StopCondition_RunCount = 2

    assert not _handle_after_run(harness.runner)
    assert harness.runner.run_count == 1
    assert harness.config.StopCondition_RunCount == 1


def test_after_run_stops_when_stop_condition_triggers() -> None:
    harness = _make_runner(stop_triggered=True)
    harness.config.StopCondition_RunCount = 2

    assert _handle_after_run(harness.runner)
    assert harness.runner.run_count == 1
    assert harness.config.StopCondition_RunCount == 1


def test_after_run_stops_on_one_time_stage() -> None:
    harness = _make_runner()
    harness.campaign.config.MAP_IS_ONE_TIME_STAGE = True

    assert _handle_after_run(harness.runner)
    assert harness.campaign.map_stop_calls == 1


def test_after_run_stops_on_stage_loop() -> None:
    harness = _make_runner()
    harness.runner.is_stage_loop = True

    assert _handle_after_run(harness.runner)


def test_after_run_stops_on_scheduler_switch() -> None:
    harness = _make_runner()
    harness.config.is_task_switched = True

    with pytest.raises(_TaskStopped):
        _handle_after_run(harness.runner)

    assert harness.campaign.auto_search_exit_calls == 1
    assert harness.config.task_stop_calls == 1


def test_ensure_run_ui_takes_fresh_screenshot_when_needed() -> None:
    harness = _make_ui_runner()
    harness.device.has_cached_image = False

    _ensure_run_ui(harness.runner, mode="hard")

    assert harness.device.stuck_clear_calls == 1
    assert harness.device.click_clear_calls == 1
    assert harness.device.screenshot_calls == 1
    assert harness.campaign.device.image == "fresh"
    assert harness.campaign.ensure_calls == [("d3", "hard")]
    assert harness.hooks.disable_raid_calls == 1
    assert harness.hooks.commission_notice_calls == 1


def test_ensure_run_ui_retreats_when_already_in_map() -> None:
    harness = _make_ui_runner()
    harness.campaign.in_map = True

    _ensure_run_ui(harness.runner)

    assert harness.campaign.withdraw_calls == 1
    assert harness.campaign.ensure_calls == [("d3", "normal")]


def test_ensure_run_ui_keeps_usable_auto_search_menu() -> None:
    harness = _make_ui_runner(auto_search_continue=True)
    harness.campaign.in_auto_search_menu = True

    _ensure_run_ui(harness.runner)

    assert harness.campaign.ensure_calls == []


def test_ensure_run_ui_closes_unusable_auto_search_menu() -> None:
    harness = _make_ui_runner(auto_search_continue=False)
    harness.campaign.in_auto_search_menu = True

    _ensure_run_ui(harness.runner)

    assert harness.campaign.ensure_calls == [("d3", "normal")]
