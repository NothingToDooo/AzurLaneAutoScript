import pytest

from module.adapters.campaign_mumu12 import (
    CampaignRuntimeEvidenceError,
    DeclarativeCampaignMapRuntime,
    Mumu12HardCampaignSession,
)
from module.adapters.campaign_runtime_hard import CampaignClearModeExecutor
from module.adapters.campaign_runtime_profile import RuntimeSessionOutcome
from module.adapters.campaign_runtime_session import (
    RuntimeProfileLease,
    RuntimeProfileLeaseState,
)
from module.application import AbortRequested, AbortToken
from module.base.button import Button
from module.content.campaign_session import CampaignRunVariant
from module.content.models import StageRef
from module.device.device import Device
from module.exception import CampaignEnd
from module.map.map_base import CampaignMap


class _SessionManager:
    def __init__(
        self,
        events: list[object],
        *,
        end_error: BaseException | None = None,
        reset_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.end_error = end_error
        self.reset_error = reset_error

    def begin_session(self) -> None:
        self.events.append("lease.begin")

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        self.events.append(("lease.end", outcome))
        if self.end_error is not None:
            raise self.end_error

    def reset(self) -> None:
        self.events.append("lease.reset")
        if self.reset_error is not None:
            raise self.reset_error


class _Cancellation:
    def __init__(
        self,
        events: list[object],
        *,
        abort_on_check: int | None = None,
    ) -> None:
        self.events = events
        self.abort_on_check = abort_on_check
        self.checks = 0
        self.error = AbortRequested("test cancellation")

    def raise_if_requested(self) -> None:
        self.checks += 1
        self.events.append(("cancel.check", self.checks))
        if self.checks == self.abort_on_check:
            raise self.error


class _Runtime(DeclarativeCampaignMapRuntime):
    def __init__(
        self,
        events: list[object],
        lease: RuntimeProfileLease,
        *,
        map_is_auto_search: bool = True,
        campaign_end_after: int | None = 2,
        errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.events = events
        self.MAP = CampaignMap("hard-attempt-test")
        self.map = CampaignMap("hard-attempt-stale")
        self._session_variant = CampaignRunVariant.NORMAL
        self._map_is_clear_mode = False
        self.map_is_auto_search = map_is_auto_search
        self._battle_count = 9
        self.campaign_end_after = campaign_end_after
        self.errors = {} if errors is None else errors
        self.battle_calls = 0
        self.selected_entrance = _entrance()
        self.stage_navigator = self
        self._hard_behavior = object.__new__(CampaignClearModeExecutor)
        self._runtime_profile_lease = lease

    def select(
        self,
        name: str,
        mode: str = "normal",
        *,
        skip_first_screenshot: bool = True,
    ) -> Button:
        del name, mode, skip_first_screenshot
        return self.selected_entrance

    @property
    def session_variant(self) -> CampaignRunVariant:
        return self._session_variant

    @session_variant.setter
    def session_variant(self, value: CampaignRunVariant) -> None:
        self.events.append(("runtime.session_variant", value))
        self._session_variant = value

    @property
    def map_is_clear_mode(self) -> bool:
        return self._map_is_clear_mode

    @map_is_clear_mode.setter
    def map_is_clear_mode(self, value: bool) -> None:
        self.events.append(("runtime.map_is_clear_mode", value))
        self._map_is_clear_mode = value

    @property
    def battle_count(self) -> int:
        return self._battle_count

    @battle_count.setter
    def battle_count(self, value: int) -> None:
        self.events.append(("runtime.battle_count", value))
        self._battle_count = value

    def enter_map(self, button: Button, mode: str = "normal", *, skip_first_screenshot: bool = True) -> bool:
        self.events.append(("runtime.enter_map", button.area, mode, skip_first_screenshot))
        self._raise_error("enter_map")
        return True

    def lv_reset(self) -> None:
        self.events.append("runtime.lv_reset")
        self._raise_error("lv_reset")

    def lv_get(self, *, after_battle: bool = False) -> None:
        del after_battle
        self.events.append("runtime.lv_get")
        self._raise_error("lv_get")

    def auto_search_execute_a_battle(self) -> None:
        self.battle_calls += 1
        self.events.append(("runtime.battle", self.battle_calls))
        self._raise_error("battle")
        if self.battle_calls == self.campaign_end_after:
            raise CampaignEnd

    def ensure_auto_search_exit(self, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.events.append("runtime.exit_ui")
        return True

    def _raise_error(self, phase: str) -> None:
        error = self.errors.get(phase)
        if error is not None:
            raise error


def _entrance() -> Button:
    return Button(
        area=(1, 2, 3, 4),
        color=(0, 0, 0),
        button=(5, 6, 7, 8),
        name="HARD_ENTRANCE",
    )


def _build_session(
    *,
    map_is_auto_search: bool = True,
    campaign_end_after: int | None = 2,
    runtime_errors: dict[str, BaseException] | None = None,
    end_error: BaseException | None = None,
    reset_error: BaseException | None = None,
) -> tuple[
    Mumu12HardCampaignSession,
    _Runtime,
    RuntimeProfileLease,
    _SessionManager,
    list[object],
]:
    events: list[object] = []
    manager = _SessionManager(events, end_error=end_error, reset_error=reset_error)
    lease = RuntimeProfileLease(manager)
    runtime = _Runtime(
        events,
        lease,
        map_is_auto_search=map_is_auto_search,
        campaign_end_after=campaign_end_after,
        errors=runtime_errors,
    )
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    session = Mumu12HardCampaignSession.open(
        runtime,
        device,
        StageRef("campaign_main", "11-4"),
        AbortToken(),
        lambda _device: 1,
    )
    events.clear()
    return session, runtime, lease, manager, events


def test_success_runs_the_complete_attempt_in_order_and_closes_completed() -> None:
    session, runtime, lease, _, events = _build_session()
    entrance = runtime.selected_entrance
    cancellation = _Cancellation(events)

    session.execute(cancellation)

    assert events == [
        ("cancel.check", 1),
        ("runtime.session_variant", CampaignRunVariant.LOOP),
        ("runtime.map_is_clear_mode", True),
        "lease.begin",
        ("runtime.enter_map", entrance.button, "hard", True),
        ("runtime.battle_count", 0),
        "runtime.lv_reset",
        "runtime.lv_get",
        ("cancel.check", 2),
        ("runtime.battle", 1),
        ("cancel.check", 3),
        ("runtime.battle", 2),
        ("lease.end", RuntimeSessionOutcome.COMPLETED),
        "lease.reset",
    ]
    assert entrance.area == entrance.button
    assert runtime.session_variant is CampaignRunVariant.LOOP
    assert runtime.map_is_clear_mode is True
    assert runtime.map is runtime.MAP
    assert runtime.battle_count == 0
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_pre_cancel_does_not_consume_or_mutate_the_ready_session() -> None:
    session, runtime, lease, _, events = _build_session(campaign_end_after=1)
    entrance = runtime.selected_entrance
    cancelled = _Cancellation(events, abort_on_check=1)

    with pytest.raises(AbortRequested) as raised:
        session.execute(cancelled)

    assert raised.value is cancelled.error
    assert events == [("cancel.check", 1)]
    assert runtime.session_variant is CampaignRunVariant.NORMAL
    assert runtime.map_is_clear_mode is False
    assert runtime.battle_count == 9
    assert entrance.area == (1, 2, 3, 4)
    assert lease.state is RuntimeProfileLeaseState.READY

    session.execute(_Cancellation(events))
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_mid_attempt_cancel_closes_interrupted_after_the_committed_battle() -> None:
    session, runtime, lease, _, events = _build_session(campaign_end_after=None)
    cancellation = _Cancellation(events, abort_on_check=3)

    with pytest.raises(AbortRequested) as raised:
        session.execute(cancellation)

    assert raised.value is cancellation.error
    assert runtime.battle_calls == 1
    assert events[-2:] == [
        ("lease.end", RuntimeSessionOutcome.INTERRUPTED),
        "lease.reset",
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_unexpected_attempt_error_closes_failed_and_preserves_the_error() -> None:
    body_error = OSError("battle failed")
    session, _, lease, _, events = _build_session(runtime_errors={"battle": body_error})

    with pytest.raises(OSError, match="battle failed") as raised:
        session.execute(_Cancellation(events))

    assert raised.value is body_error
    assert events[-2:] == [
        ("lease.end", RuntimeSessionOutcome.FAILED),
        "lease.reset",
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_missing_game_auto_search_evidence_closes_failed() -> None:
    session, runtime, lease, _, events = _build_session(map_is_auto_search=False)

    with pytest.raises(CampaignRuntimeEvidenceError, match="clear-mode auto search"):
        session.execute(_Cancellation(events))

    assert runtime.map is not runtime.MAP
    assert runtime.battle_calls == 0
    assert events[-2:] == [
        ("lease.end", RuntimeSessionOutcome.FAILED),
        "lease.reset",
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_attempt_without_settlement_fails_after_exactly_twenty_battles() -> None:
    session, runtime, lease, _, events = _build_session(campaign_end_after=None)
    cancellation = _Cancellation(events)

    with pytest.raises(CampaignRuntimeEvidenceError, match="within 20 battles"):
        session.execute(cancellation)

    assert runtime.battle_calls == 20
    assert cancellation.checks == 21
    assert events[-2:] == [
        ("lease.end", RuntimeSessionOutcome.FAILED),
        "lease.reset",
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


@pytest.mark.parametrize("phase", ["enter_map", "lv_reset", "lv_get"])
def test_campaign_end_only_settles_when_raised_by_a_battle(phase: str) -> None:
    campaign_end = CampaignEnd()
    session, runtime, lease, _, events = _build_session(runtime_errors={phase: campaign_end})

    with pytest.raises(CampaignEnd) as raised:
        session.execute(_Cancellation(events))

    assert raised.value is campaign_end
    assert runtime.battle_calls == 0
    assert events[-2:] == [
        ("lease.end", RuntimeSessionOutcome.FAILED),
        "lease.reset",
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_body_and_cleanup_failure_are_preserved_in_occurrence_order() -> None:
    body_error = ValueError("body failed")
    cleanup_error = OSError("end failed")
    session, _, lease, _, events = _build_session(
        runtime_errors={"battle": body_error},
        end_error=cleanup_error,
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        session.execute(_Cancellation(events))

    assert raised.value.exceptions == (body_error, cleanup_error)
    assert events[-2:] == [
        ("lease.end", RuntimeSessionOutcome.FAILED),
        "lease.reset",
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_completed_cleanup_failure_closes_once_and_release_is_a_noop() -> None:
    cleanup_error = OSError("completed cleanup failed")
    session, _, lease, _, events = _build_session(
        campaign_end_after=1,
        end_error=cleanup_error,
    )

    with pytest.raises(OSError, match="completed cleanup failed") as raised:
        session.execute(_Cancellation(events))

    assert raised.value is cleanup_error
    assert events[-2:] == [
        ("lease.end", RuntimeSessionOutcome.COMPLETED),
        "lease.reset",
    ]
    assert events.count(("lease.end", RuntimeSessionOutcome.COMPLETED)) == 1
    assert events.count("lease.reset") == 1
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    session.close()
    assert events.count(("lease.end", RuntimeSessionOutcome.COMPLETED)) == 1
    assert events.count("lease.reset") == 1


def test_session_rejects_a_second_execute_before_runtime_mutation() -> None:
    session, runtime, lease, _, events = _build_session(campaign_end_after=1)
    session.execute(_Cancellation(events))
    events.clear()
    entrance = runtime.selected_entrance
    area = entrance.area

    with pytest.raises(CampaignRuntimeEvidenceError, match="only once"):
        session.execute(_Cancellation(events))

    assert events == []
    assert entrance.area == area
    assert runtime.session_variant is CampaignRunVariant.LOOP
    assert runtime.map_is_clear_mode is True
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_release_discards_a_ready_lease_once() -> None:
    session, runtime, lease, _, events = _build_session()

    session.close()
    assert events == ["lease.reset"]
    events.clear()
    entrance = runtime.selected_entrance
    with pytest.raises(CampaignRuntimeEvidenceError, match="only once"):
        session.execute(_Cancellation(events))
    session.close()

    assert events == []
    assert entrance.area == (1, 2, 3, 4)
    assert runtime.session_variant is CampaignRunVariant.NORMAL
    assert runtime.map_is_clear_mode is False
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_release_interrupts_an_active_lease_once() -> None:
    session, _, lease, _, events = _build_session()
    lease.start()
    events.clear()

    session.close()
    session.close()

    assert events == [
        ("lease.end", RuntimeSessionOutcome.INTERRUPTED),
        "lease.reset",
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_release_is_a_noop_for_an_already_closed_lease() -> None:
    session, _, lease, _, events = _build_session()
    lease.discard()
    events.clear()

    session.close()
    session.close()

    assert events == []
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_execute_validates_cancellation_before_consuming_the_session() -> None:
    session, _, lease, _, events = _build_session(campaign_end_after=1)

    with pytest.raises(TypeError, match="cancellation source"):
        session.execute(object())  # ty: ignore[invalid-argument-type] - 验证运行时边界。

    assert events == []
    assert lease.state is RuntimeProfileLeaseState.READY
    session.execute(_Cancellation(events))


def test_exit_ui_remains_available_after_the_attempt_closes() -> None:
    session, _, lease, _, events = _build_session(campaign_end_after=1)
    session.execute(_Cancellation(events))
    events.clear()

    session.exit_ui(_Cancellation(events))

    assert events == [
        ("cancel.check", 1),
        "runtime.exit_ui",
        ("cancel.check", 2),
    ]
    assert lease.state is RuntimeProfileLeaseState.CLOSED


def test_release_propagates_cleanup_failure_but_remains_idempotent() -> None:
    cleanup_error = OSError("reset failed")
    session, _, lease, manager, events = _build_session(reset_error=cleanup_error)

    with pytest.raises(OSError, match="reset failed") as raised:
        session.close()

    assert raised.value is cleanup_error
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    manager.reset_error = None
    session.close()
    assert events == ["lease.reset"]
