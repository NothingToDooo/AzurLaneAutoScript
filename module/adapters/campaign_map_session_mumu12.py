from typing import TYPE_CHECKING, Protocol

from module.adapters.campaign_map_initialization import (
    CampaignMapInitializationRuntime,
    CampaignMapInitializationService,
)
from module.adapters.campaign_runtime_profile import RuntimeSessionOutcome
from module.adapters.campaign_runtime_session import RuntimeProfileLease
from module.adapters.campaign_submarine import (
    CampaignSubmarineFreshCombatService,
    SubmarineFreshCombatRuntime,
)
from module.application import AbortRequested
from module.base.failure import preserve_cleanup_failure
from module.content.campaign_session import CampaignRunVariant
from module.logger import logger

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap


class Mumu12CampaignMapSessionRuntime(
    SubmarineFreshCombatRuntime,
    CampaignMapInitializationRuntime,
    Protocol,
):
    MAP: CampaignMap
    session_variant: CampaignRunVariant
    map_is_clear_mode: bool

    def map_data_init(self, map_: CampaignMap | None) -> None: ...

    def map_control_init(self) -> None: ...


class Mumu12CampaignMapSessionOwner:
    """持有一张普通 campaign 地图的 profile session 与地图初始化状态。"""

    __slots__ = ("_fresh_combat", "_initialization", "_lease", "_runtime")

    def __init__(
        self,
        runtime: Mumu12CampaignMapSessionRuntime,
        lease: RuntimeProfileLease,
        fresh_combat: CampaignSubmarineFreshCombatService,
        initialization: CampaignMapInitializationService,
    ) -> None:
        if isinstance(runtime, type) or any(
            not callable(getattr(runtime, method, None)) for method in ("map_data_init", "map_control_init")
        ):
            message = "campaign map session owner requires a map runtime"
            raise TypeError(message)
        if not isinstance(lease, RuntimeProfileLease):
            message = "campaign map session owner requires a RuntimeProfileLease"
            raise TypeError(message)
        if not isinstance(fresh_combat, CampaignSubmarineFreshCombatService):
            message = "campaign map session owner requires a typed fresh combat service"
            raise TypeError(message)
        if not isinstance(initialization, CampaignMapInitializationService):
            message = "campaign map session owner requires a typed map initialization service"
            raise TypeError(message)
        self._runtime = runtime
        self._lease = lease
        self._fresh_combat = fresh_combat
        self._initialization = initialization

    @property
    def active(self) -> bool:
        return self._lease.active

    def initialize(self, variant: CampaignRunVariant) -> None:
        if not isinstance(variant, CampaignRunVariant):
            message = "campaign map session initialization requires a CampaignRunVariant"
            raise TypeError(message)
        runtime = self._runtime
        runtime.session_variant = variant
        runtime.map_is_clear_mode = variant is CampaignRunVariant.LOOP
        self._lease.start()
        try:
            self._fresh_combat.start(runtime)
            logger.hr("Map init")
            runtime.map_data_init(runtime.MAP)
            self._initialization.pre_control(runtime)
            runtime.map_control_init()
            self._initialization.post_control(runtime)
        except BaseException as error:
            outcome = (
                RuntimeSessionOutcome.INTERRUPTED if isinstance(error, AbortRequested) else RuntimeSessionOutcome.FAILED
            )
            preserve_cleanup_failure(
                error,
                lambda: self.close(outcome),
                message="campaign map session initialization and cleanup both failed",
            )
            raise

    def close(self, outcome: RuntimeSessionOutcome) -> None:
        self._lease.close(outcome)

    def discard(self) -> None:
        self._lease.discard()
