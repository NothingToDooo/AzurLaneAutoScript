from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import pytest

from module.combat.assets import GET_ITEMS_1
from module.daemon.daemon import AzurLaneDaemon
from module.handler.mystery import MysteryHandler
from module.handler.mystery_item import (
    STANDARD_MYSTERY_ITEM_SERVICE,
    MysteryItemOutcome,
    MysteryItemRequest,
    MysteryItemRuntime,
    MysteryItemService,
    MysteryKind,
    MysteryResult,
)
from module.map.fleet import Fleet
from module.os.fleet import OSFleet

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.map.fleet import _GotoState
    from module.map_detection.grid import Grid


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.sleeps: list[float] = []
        self.screenshots = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def screenshot(self) -> None:
        self.screenshots += 1


class _StandardRuntime:
    def __init__(self) -> None:
        self.config = SimpleNamespace(MAP_MYSTERY_MAP_CLICK=True)
        self.device = _Device()
        self.visible = False
        self.appear_calls: list[object] = []
        self.strategy_close_calls = 0

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, interval, similarity, threshold
        self.appear_calls.append(button)
        return self.visible and button is GET_ITEMS_1

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.strategy_close_calls += 1


class _RecordingService(MysteryItemService):
    def __init__(self, outcome: MysteryItemOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[MysteryItemRuntime, MysteryItemRequest]] = []

    @override
    def handle(
        self,
        runtime: MysteryItemRuntime,
        request: MysteryItemRequest,
    ) -> MysteryItemOutcome:
        self.calls.append((runtime, request))
        return self.outcome


class _MysteryHarness(MysteryHandler):
    def __init__(self, service: MysteryItemService) -> None:
        self._mystery_item_service = service
        self.ammo_calls = 0
        self.carrier_calls = 0

    @override
    def handle_mystery_ammo(self) -> bool:
        self.ammo_calls += 1
        return True

    @override
    def handle_mystery_carrier(self) -> bool:
        self.carrier_calls += 1
        return True


class _Grid:
    button = (0, 0, 1, 1)

    @staticmethod
    def predict_fleet() -> bool:
        return True

    @staticmethod
    def predict_current_fleet() -> bool:
        return True


def test_standard_mystery_item_preserves_button_identity_and_counts() -> None:
    runtime = _StandardRuntime()
    runtime.visible = True
    button = cast("Grid", _Grid())
    request = MysteryItemRequest(button=button)

    outcome = STANDARD_MYSTERY_ITEM_SERVICE.handle(cast("MysteryItemRuntime", runtime), request)

    assert outcome == MysteryItemOutcome(handled=True, counts_toward_mystery=True)
    assert runtime.appear_calls == [GET_ITEMS_1]
    assert runtime.device.clicks == [button]
    assert runtime.device.sleeps == [0.5]
    assert runtime.device.screenshots == 1
    assert runtime.strategy_close_calls == 1
    with pytest.raises(FrozenInstanceError):
        setattr(  # ruff:ignore[set-attr-with-constant] - intentional frozen mutation probe
            request,
            "button",
            None,
        )


def test_mystery_item_outcome_rejects_counting_an_unhandled_popup() -> None:
    with pytest.raises(ValueError, match="unhandled mystery item outcome cannot count"):
        MysteryItemOutcome(handled=False, counts_toward_mystery=True)


def test_handled_non_counting_item_stops_fallback_handlers() -> None:
    service = _RecordingService(MysteryItemOutcome(handled=True, counts_toward_mystery=False))
    handler = _MysteryHarness(service)
    button = cast("Grid", _Grid())

    result = handler.handle_mystery(button=button)

    assert result == MysteryResult(MysteryKind.GET_ITEM, counts_toward_mystery=False)
    assert service.calls[0][0] is handler
    assert service.calls[0][1].button is button
    assert handler.ammo_calls == 0
    assert handler.carrier_calls == 0


@pytest.mark.parametrize("scenario", [(False, 4), (True, 5)])
def test_fleet_records_handled_mystery_but_only_increments_count_when_requested(
    scenario: tuple[bool, int],
) -> None:
    counts_toward_mystery, expected_count = scenario
    result = MysteryResult(
        kind=MysteryKind.GET_ITEM,
        counts_toward_mystery=counts_toward_mystery,
    )
    handled_buttons: list[object] = []

    def handle_mystery(*, button: object) -> MysteryResult:
        handled_buttons.append(button)
        return result

    fleet = SimpleNamespace(mystery_count=4, handle_mystery=handle_mystery)
    state = SimpleNamespace(grid=object(), result="nothing", result_mystery="")

    Fleet._goto_handle_mystery(  # ruff:ignore[private-member-access] - isolates state transition
        cast("Fleet", fleet),
        cast("_GotoState", state),
    )

    assert handled_buttons == [state.grid]
    assert fleet.mystery_count == expected_count
    assert state.result == "mystery"
    assert state.result_mystery == "get_item"


@pytest.mark.parametrize(
    "outcome",
    [
        MysteryItemOutcome(handled=False, counts_toward_mystery=False),
        MysteryItemOutcome(handled=True, counts_toward_mystery=True),
    ],
)
def test_daemon_reads_typed_mystery_outcome(outcome: MysteryItemOutcome) -> None:
    daemon = SimpleNamespace(
        appear_then_click=lambda *_args, **_kwargs: False,
        handle_mystery_items=lambda: outcome,
    )

    assert AzurLaneDaemon.handle_daemon_map_operation(cast("AzurLaneDaemon", daemon)) is outcome.handled


def test_os_mystery_override_returns_typed_result() -> None:
    runtime = SimpleNamespace(_os_map_event_handled=True)
    button = cast("Grid", _Grid())

    result = OSFleet.handle_mystery(cast("OSFleet", runtime), button=button)

    assert result == MysteryResult(MysteryKind.GET_ITEM, counts_toward_mystery=True)
