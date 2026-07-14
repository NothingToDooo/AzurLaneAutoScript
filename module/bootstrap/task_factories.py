from dataclasses import dataclass

from module.gameplay.activity_factories import ActivityFactoryDependencies, build_activity_factories
from module.gameplay.campaign_factories import CampaignFactoryDependencies, build_campaign_factories
from module.gameplay.composite_factories import CompositeWorkflows, build_composite_factories
from module.gameplay.encounter_factories import EncounterWorkflows, build_encounter_factories
from module.gameplay.facility_factories import FacilityWorkflows, build_facility_factories
from module.gameplay.market_factories import MarketWorkflows, build_market_factories
from module.gameplay.opsi_factories import OpsiWorkflows, build_opsi_factories
from module.maintenance import MaintenanceServices, build_maintenance_factories
from module.runtime import TaskFactoryRegistry, compose_task_factories


@dataclass(frozen=True, slots=True)
class GameTaskDependencies:
    maintenance: MaintenanceServices
    facility: FacilityWorkflows
    composite: CompositeWorkflows
    market: MarketWorkflows
    encounter: EncounterWorkflows
    campaign: CampaignFactoryDependencies
    opsi: OpsiWorkflows
    activity: ActivityFactoryDependencies

    def __post_init__(self) -> None:
        expected = (
            ("maintenance", self.maintenance, MaintenanceServices),
            ("facility", self.facility, FacilityWorkflows),
            ("composite", self.composite, CompositeWorkflows),
            ("market", self.market, MarketWorkflows),
            ("encounter", self.encounter, EncounterWorkflows),
            ("campaign", self.campaign, CampaignFactoryDependencies),
            ("opsi", self.opsi, OpsiWorkflows),
            ("activity", self.activity, ActivityFactoryDependencies),
        )
        for field_name, value, expected_type in expected:
            if not isinstance(value, expected_type):
                message = f"{field_name} must be a {expected_type.__name__}"
                raise TypeError(message)


def build_game_task_registry(
    dependencies: GameTaskDependencies,
    *,
    content_revision: str,
    client_ui_revision: str,
) -> TaskFactoryRegistry:
    """唯一的游戏 Task composition root；领域 factory 必须精确覆盖 catalog。"""
    if not isinstance(dependencies, GameTaskDependencies):
        message = "dependencies must be GameTaskDependencies"
        raise TypeError(message)
    return compose_task_factories(
        (
            build_maintenance_factories(dependencies.maintenance),
            build_facility_factories(dependencies.facility),
            build_composite_factories(dependencies.composite),
            build_market_factories(dependencies.market),
            build_encounter_factories(dependencies.encounter),
            build_campaign_factories(dependencies.campaign),
            build_opsi_factories(dependencies.opsi),
            build_activity_factories(dependencies.activity),
        ),
        content_revision=content_revision,
        client_ui_revision=client_ui_revision,
    )
