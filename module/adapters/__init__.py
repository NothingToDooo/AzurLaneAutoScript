"""连接领域端口与真实客户端实现的 adapter。"""

from module.adapters.activity_mumu12 import build_mumu12_activity_workflows
from module.adapters.campaign_live import (
    CampaignGrid,
    CampaignMapAdapterError,
    CampaignMapRuntime,
    CampaignMapRuntimeSource,
    CampaignRuntimeUnitSource,
    ExistingCampaignMapAdapter,
    build_existing_campaign_map_workflow,
)
from module.adapters.campaign_mumu12 import (
    Mumu12CampaignRuntimeProvider,
    Mumu12HardCampaignPort,
    build_mumu12_campaign_dependencies,
)
from module.adapters.campaign_program_mumu12 import Mumu12CampaignBattleProgramExecutor
from module.adapters.composite_mumu12 import build_mumu12_composite_workflows
from module.adapters.encounter_mumu12 import build_mumu12_encounter_workflows
from module.adapters.facility_live import (
    CommissionEvidence,
    LiveCommissionWorkflow,
    LiveResearchWorkflow,
    LiveTacticalWorkflow,
    ResearchQueueEvidence,
    TacticalEvidence,
)
from module.adapters.facility_mumu12 import build_mumu12_facility_workflows
from module.adapters.gems_mumu12 import Mumu12GemsFleetReplacementExecutor
from module.adapters.maintenance_mumu12 import build_mumu12_maintenance_services
from module.adapters.market_mumu12 import build_mumu12_market_workflows
from module.adapters.mumu12 import CancellationAwareMumu12Device
from module.adapters.opsi_live import (
    LiveOperationSirenWorkflow,
    LiveOpsiStep,
    OpsiLiveClock,
    OpsiLiveStepDriver,
    OpsiWorldScheduleSource,
)
from module.adapters.opsi_mumu12 import (
    Mumu12OperationSirenStepDriver,
    Mumu12OpsiWorldScheduleSource,
    build_mumu12_operation_siren_workflow,
    build_mumu12_opsi_workflows,
)

__all__ = [
    "CampaignGrid",
    "CampaignMapAdapterError",
    "CampaignMapRuntime",
    "CampaignMapRuntimeSource",
    "CampaignRuntimeUnitSource",
    "CancellationAwareMumu12Device",
    "CommissionEvidence",
    "ExistingCampaignMapAdapter",
    "LiveCommissionWorkflow",
    "LiveOperationSirenWorkflow",
    "LiveOpsiStep",
    "LiveResearchWorkflow",
    "LiveTacticalWorkflow",
    "Mumu12CampaignBattleProgramExecutor",
    "Mumu12CampaignRuntimeProvider",
    "Mumu12GemsFleetReplacementExecutor",
    "Mumu12HardCampaignPort",
    "Mumu12OperationSirenStepDriver",
    "Mumu12OpsiWorldScheduleSource",
    "OpsiLiveClock",
    "OpsiLiveStepDriver",
    "OpsiWorldScheduleSource",
    "ResearchQueueEvidence",
    "TacticalEvidence",
    "build_existing_campaign_map_workflow",
    "build_mumu12_activity_workflows",
    "build_mumu12_campaign_dependencies",
    "build_mumu12_composite_workflows",
    "build_mumu12_encounter_workflows",
    "build_mumu12_facility_workflows",
    "build_mumu12_maintenance_services",
    "build_mumu12_market_workflows",
    "build_mumu12_operation_siren_workflow",
    "build_mumu12_opsi_workflows",
]
