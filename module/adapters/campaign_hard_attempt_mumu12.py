from functools import partial
from typing import TYPE_CHECKING, Protocol

from module.adapters.campaign_runtime_profile import RuntimeSessionOutcome
from module.adapters.campaign_runtime_session import RuntimeProfileLease, RuntimeProfileLeaseState
from module.application import AbortRequested, CancellationSource
from module.base.button import Button
from module.base.failure import preserve_cleanup_failure
from module.content.campaign_session import CampaignRunVariant
from module.exception import CampaignEnd

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap


class Mumu12CampaignHardAttemptError(RuntimeError):
    pass


class Mumu12CampaignHardAttemptRuntime(Protocol):
    map: CampaignMap
    session_variant: CampaignRunVariant
    map_is_clear_mode: bool
    map_is_auto_search: bool
    battle_count: int

    @property
    def MAP(self) -> CampaignMap: ...  # ruff:ignore[invalid-function-name] - 沿用引擎公开的地图常量名。

    def enter_map(self, button: Button, mode: str = "normal", *, skip_first_screenshot: bool = True) -> bool: ...

    def lv_reset(self) -> None: ...

    def lv_get(self) -> None: ...

    def auto_search_execute_a_battle(self) -> object: ...


class Mumu12CampaignHardAttemptOwner:
    """持有一次困难图 attempt 的运行状态和 profile session。"""

    __slots__ = ("_consumed", "_lease", "_runtime")

    def __init__(
        self,
        runtime: Mumu12CampaignHardAttemptRuntime,
        lease: RuntimeProfileLease,
    ) -> None:
        attributes = (
            "MAP",
            "session_variant",
            "map_is_clear_mode",
            "map_is_auto_search",
            "battle_count",
        )
        methods = (
            "enter_map",
            "lv_reset",
            "lv_get",
            "auto_search_execute_a_battle",
        )
        if (
            isinstance(runtime, type)
            or any(not hasattr(runtime, attribute) for attribute in attributes)
            or any(not callable(getattr(runtime, method, None)) for method in methods)
        ):
            message = "hard campaign attempt owner requires a MuMu12 hard attempt runtime"
            raise TypeError(message)
        if not isinstance(lease, RuntimeProfileLease):
            message = "hard campaign attempt owner requires a RuntimeProfileLease"
            raise TypeError(message)
        if lease.state is not RuntimeProfileLeaseState.READY:
            message = "hard campaign attempt owner requires a ready RuntimeProfileLease"
            raise Mumu12CampaignHardAttemptError(message)
        self._runtime = runtime
        self._lease = lease
        self._consumed = False

    def execute(self, entrance: Button, cancellation: CancellationSource) -> None:
        if self._consumed or self._lease.state is not RuntimeProfileLeaseState.READY:
            message = "hard campaign attempt owner can execute only once"
            raise Mumu12CampaignHardAttemptError(message)
        if not isinstance(entrance, Button):
            message = "hard campaign attempt requires a Button entrance"
            raise TypeError(message)
        if isinstance(cancellation, type) or not callable(getattr(cancellation, "raise_if_requested", None)):
            message = "hard campaign attempt requires a cancellation source"
            raise TypeError(message)

        cancellation.raise_if_requested()
        self._consumed = True
        runtime = self._runtime
        runtime.session_variant = CampaignRunVariant.LOOP
        runtime.map_is_clear_mode = True
        self._lease.start()
        try:
            self._execute_body(entrance, cancellation)
        except AbortRequested as error:
            preserve_cleanup_failure(
                error,
                partial(self._lease.close, RuntimeSessionOutcome.INTERRUPTED),
                message="cancelled hard campaign attempt and cleanup both failed",
            )
            raise
        except BaseException as error:
            preserve_cleanup_failure(
                error,
                partial(self._lease.close, RuntimeSessionOutcome.FAILED),
                message="hard campaign attempt and cleanup both failed",
            )
            raise
        self._lease.close(RuntimeSessionOutcome.COMPLETED)

    def _execute_body(self, entrance: Button, cancellation: CancellationSource) -> None:
        runtime = self._runtime
        entrance.area = entrance.button
        runtime.enter_map(entrance, mode="hard")
        if not runtime.map_is_auto_search:
            message = "hard campaign attempt requires the game's clear-mode auto search"
            raise Mumu12CampaignHardAttemptError(message)
        runtime.map = runtime.MAP
        runtime.battle_count = 0
        runtime.lv_reset()
        runtime.lv_get()
        for _ in range(20):
            cancellation.raise_if_requested()
            try:
                runtime.auto_search_execute_a_battle()
            except CampaignEnd:
                return
        message = "hard campaign attempt did not reach settlement within 20 battles"
        raise Mumu12CampaignHardAttemptError(message)

    def release(self) -> None:
        self._consumed = True
        if self._lease.active:
            self._lease.close(RuntimeSessionOutcome.INTERRUPTED)
            return
        self._lease.discard()
