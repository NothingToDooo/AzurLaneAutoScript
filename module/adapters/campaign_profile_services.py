from dataclasses import dataclass
from typing import TYPE_CHECKING

from module.adapters.campaign_clear_mode_config import build_campaign_clear_mode_config_service
from module.adapters.campaign_event_ui import build_campaign_event_ui_services
from module.adapters.campaign_fleet_preparation import build_campaign_fleet_preparation_service
from module.adapters.campaign_map_initialization import build_campaign_map_initialization_service
from module.adapters.campaign_map_observer import build_campaign_map_observer
from module.adapters.campaign_map_swipe import build_campaign_map_swipe_service
from module.adapters.campaign_mystery_item import build_campaign_mystery_item_service
from module.adapters.campaign_program_capabilities import build_campaign_program_capability_reader
from module.adapters.campaign_runtime_hard import build_campaign_clear_mode_behavior
from module.adapters.campaign_runtime_profile import CampaignRuntimeProfileManager
from module.adapters.campaign_strategy_set import build_campaign_strategy_set_service
from module.adapters.campaign_submarine import build_campaign_submarine_services
from module.content.runtime_profile import RuntimeExecutorKind

if TYPE_CHECKING:
    from module.adapters.campaign_clear_mode_config import CampaignClearModeConfigService
    from module.adapters.campaign_event_ui import CampaignEventUiServices
    from module.adapters.campaign_map_initialization import CampaignMapInitializationService
    from module.adapters.campaign_program_capabilities import CampaignProgramCapabilityReader
    from module.adapters.campaign_runtime_hard import CampaignClearModeExecutor
    from module.adapters.campaign_submarine import CampaignSubmarineServices
    from module.handler.mystery_item import MysteryItemService
    from module.handler.strategy_set import StrategySetService
    from module.map.map_fleet_preparation import FleetPreparationService
    from module.map.map_observer import CampaignMapObserver
    from module.map.map_swipe import MapSwipeService


@dataclass(frozen=True, slots=True)
class CampaignProfileServices:
    """一次 profile 编译产生的完整 immutable service bundle。"""

    hard_behavior: CampaignClearModeExecutor | None
    event_ui: CampaignEventUiServices
    map_observer: CampaignMapObserver
    fleet_preparation: FleetPreparationService
    submarine: CampaignSubmarineServices
    strategy_set: StrategySetService
    program_capabilities: CampaignProgramCapabilityReader
    map_swipe: MapSwipeService
    mystery_item: MysteryItemService
    map_initialization: CampaignMapInitializationService
    clear_mode_config: CampaignClearModeConfigService


def compile_campaign_profile_services(
    manager: CampaignRuntimeProfileManager,
) -> CampaignProfileServices:
    """按 profile 声明顺序一次编译全部 runtime contributor service。"""

    if not isinstance(manager, CampaignRuntimeProfileManager):
        message = "manager must be a CampaignRuntimeProfileManager"
        raise TypeError(message)

    hard_instances = manager.executor_instances(RuntimeExecutorKind.HARD_MODE)
    event_ui_instances = manager.executor_instances(RuntimeExecutorKind.EVENT_UI)
    map_observation_instances = manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION)
    mechanic_instances = manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC)
    instances_in_profile_order = manager.executor_instances_in_profile_order()

    return CampaignProfileServices(
        hard_behavior=build_campaign_clear_mode_behavior(hard_instances),
        event_ui=build_campaign_event_ui_services(event_ui_instances),
        map_observer=build_campaign_map_observer(
            map_observation_instances,
            map_clear_percentage_multiplier=manager.map_clear_percentage_multiplier,
        ),
        fleet_preparation=build_campaign_fleet_preparation_service(mechanic_instances),
        submarine=build_campaign_submarine_services(mechanic_instances),
        strategy_set=build_campaign_strategy_set_service(mechanic_instances),
        program_capabilities=build_campaign_program_capability_reader(mechanic_instances),
        map_swipe=build_campaign_map_swipe_service(mechanic_instances),
        mystery_item=build_campaign_mystery_item_service(mechanic_instances),
        map_initialization=build_campaign_map_initialization_service(instances_in_profile_order),
        clear_mode_config=build_campaign_clear_mode_config_service(instances_in_profile_order),
    )
