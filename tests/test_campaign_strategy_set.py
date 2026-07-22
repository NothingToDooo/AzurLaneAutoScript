from dataclasses import FrozenInstanceError

import pytest
from config_factory import in_memory_config

from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_strategy_set import (
    CampaignStrategySetObserverContributor,
    build_campaign_strategy_set_service,
)
from module.content.models import StageRef
from module.content.stage_loader import load_default_stage
from module.device.device import Device
from module.handler.strategy import StrategyHandler
from module.handler.strategy_set import StrategySetRequest, StrategySetRuntime
from module.map.fleet import Fleet
from module.map.fleet_navigation_ui import CampaignSubmarineMovementUi


class _RecordingStrategySetService:
    def __init__(self) -> None:
        self.runtime: StrategySetRuntime | None = None
        self.request: StrategySetRequest | None = None

    def execute(
        self,
        runtime: StrategySetRuntime,
        request: StrategySetRequest,
    ) -> None:
        self.runtime = runtime
        self.request = request


class _ObserverSource:
    def __init__(self, contributor: CampaignStrategySetObserverContributor) -> None:
        self._contributor = contributor

    @property
    def strategy_set_observer_contributor(self) -> CampaignStrategySetObserverContributor:
        return self._contributor


class _Runtime:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[tuple[str, StrategySetRequest]] = []
        self.fail = fail

    def _standard_strategy_set_execute(self, request: StrategySetRequest) -> None:
        self.events.append(("standard", request))
        if self.fail:
            message = "standard strategy failure"
            raise RuntimeError(message)


class _SubmarineGotoRuntime(Fleet):
    def __init__(self) -> None:
        self.events: list[object] = []

    def strategy_open(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.events.append("open")

    def strategy_submarine_move_enter(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.events.append("enter")

    def strategy_submarine_move_confirm(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.events.append("confirm")

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.events.append("close")

    def _standard_strategy_set_execute(self, request: StrategySetRequest) -> None:
        self.events.append(("standard", request))


def test_public_strategy_set_builds_one_frozen_request_and_preserves_parameters() -> None:
    runtime = object.__new__(StrategyHandler)
    service = _RecordingStrategySetService()
    runtime._strategy_set_service = service  # ruff:ignore[private-member-access] - verifies the public dispatch seam.

    runtime.strategy_set_execute(
        "diamond",
        sub_view=False,
        sub_hunt=True,
    )

    request = service.request
    assert service.runtime is runtime
    assert request == StrategySetRequest(
        formation="diamond",
        sub_view=False,
        sub_hunt=True,
    )
    assert request is not None
    field = "formation"
    with pytest.raises(FrozenInstanceError):
        setattr(request, field, "line_ahead")


def test_strategy_set_runs_standard_once_then_observers_in_profile_order_with_same_request() -> None:
    runtime = _Runtime()
    observed: list[tuple[str, StrategySetRequest]] = []
    service = build_campaign_strategy_set_service(
        (
            _ObserverSource(
                CampaignStrategySetObserverContributor(lambda _runtime, request: observed.append(("first", request)))
            ),
            _ObserverSource(
                CampaignStrategySetObserverContributor(lambda _runtime, request: observed.append(("second", request)))
            ),
        )
    )
    request = StrategySetRequest(sub_view=False)

    service.execute(runtime, request)

    assert runtime.events == [("standard", request)]
    assert observed == [("first", request), ("second", request)]
    assert all(observed_request is request for _, observed_request in observed)


def test_strategy_set_does_not_notify_observers_when_standard_execution_fails() -> None:
    runtime = _Runtime(fail=True)
    observed: list[StrategySetRequest] = []
    service = build_campaign_strategy_set_service(
        (_ObserverSource(CampaignStrategySetObserverContributor(lambda _runtime, request: observed.append(request))),)
    )
    request = StrategySetRequest(formation="line_ahead")

    with pytest.raises(RuntimeError, match="standard strategy failure"):
        service.execute(runtime, request)

    assert runtime.events == [("standard", request)]
    assert observed == []


@pytest.mark.parametrize(
    ("stage_id", "expected_trace"),
    [
        ("14-4", ["standard"]),
        ("15-1", ["standard", "observe"]),
    ],
)
def test_declarative_runtime_installs_real_profile_strategy_observers(
    stage_id: str,
    expected_trace: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    monkeypatch.setattr(
        DeclarativeCampaignMapRuntime,
        "_standard_strategy_set_execute",
        lambda _runtime, _request: trace.append("standard"),
    )
    monkeypatch.setattr(
        DeclarativeCampaignMapRuntime,
        "strategy_has_mob_move",
        lambda _runtime: trace.append("observe") or True,
    )
    runtime = DeclarativeCampaignMapRuntime(
        in_memory_config(f"strategy-set-wiring-{stage_id}", {}),
        object.__new__(Device),
        load_default_stage(StageRef("campaign_main", stage_id)),
    )

    runtime.strategy_set_execute(sub_view=False)

    assert trace == expected_trace


def test_submarine_navigation_finish_uses_the_same_observed_strategy_path() -> None:
    runtime = _SubmarineGotoRuntime()
    observed: list[StrategySetRequest] = []
    runtime._strategy_set_service = build_campaign_strategy_set_service(  # ruff:ignore[private-member-access] - verifies Fleet's production call path.
        (_ObserverSource(CampaignStrategySetObserverContributor(lambda _runtime, request: observed.append(request))),)
    )

    movement_ui = CampaignSubmarineMovementUi(runtime)
    movement_ui.navigation_submarine_open()
    movement_ui.navigation_submarine_confirm()
    movement_ui.navigation_submarine_finish()

    request = StrategySetRequest(sub_view=False)
    assert runtime.events == [
        "open",
        "enter",
        "confirm",
        ("standard", request),
        "close",
    ]
    assert observed == [request]
