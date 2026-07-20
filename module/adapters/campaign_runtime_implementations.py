from .campaign_runtime_event_ui import event_ui_runtime_executor_descriptors
from .campaign_runtime_grid_registry import grid_runtime_executor_descriptors
from .campaign_runtime_hard import hard_runtime_executor_descriptors
from .campaign_runtime_mechanics import mechanic_runtime_executor_descriptors
from .campaign_runtime_mystery import mystery_runtime_executor_descriptors
from .campaign_runtime_navigation import navigation_runtime_executor_descriptors
from .campaign_runtime_observation import observation_runtime_executor_descriptors
from .campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    RuntimeExecutorFactoryDescriptor,
)
from .campaign_runtime_semantic import semantic_runtime_executor_descriptors
from .campaign_runtime_special_early import special_early_runtime_executor_descriptors
from .campaign_runtime_special_event_ui import special_event_ui_runtime_executor_descriptors
from .campaign_runtime_war_archives import war_archives_runtime_executor_descriptors


def default_campaign_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    """返回全部固定 production implementation；profile 只能引用这里的封闭 ID。"""

    return (
        *grid_runtime_executor_descriptors(),
        *hard_runtime_executor_descriptors(),
        *semantic_runtime_executor_descriptors(),
        *mechanic_runtime_executor_descriptors(),
        *mystery_runtime_executor_descriptors(),
        *navigation_runtime_executor_descriptors(),
        *observation_runtime_executor_descriptors(),
        *event_ui_runtime_executor_descriptors(),
        *special_early_runtime_executor_descriptors(),
        *special_event_ui_runtime_executor_descriptors(),
        *war_archives_runtime_executor_descriptors(),
    )


def load_default_campaign_runtime_executor_registry() -> CampaignRuntimeExecutorRegistry:
    return CampaignRuntimeExecutorRegistry(default_campaign_runtime_executor_descriptors())
