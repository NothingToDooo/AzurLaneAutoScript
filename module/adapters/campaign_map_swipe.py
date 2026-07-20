from typing import TYPE_CHECKING, Protocol, runtime_checkable

from module.map.map_swipe import STANDARD_MAP_SWIPE_POLICY, MapSwipePolicy, MapSwipeService

from .campaign_runtime_profile import CampaignRuntimeProfileError

if TYPE_CHECKING:
    from collections.abc import Iterable


@runtime_checkable
class CampaignMapSwipePolicySource(Protocol):
    @property
    def map_swipe_policy(self) -> MapSwipePolicy: ...


def build_campaign_map_swipe_service(
    instances: Iterable[object],
) -> MapSwipeService:
    policies: list[MapSwipePolicy] = []
    for instance in instances:
        if not isinstance(instance, CampaignMapSwipePolicySource):
            continue
        policy = instance.map_swipe_policy
        if not isinstance(policy, MapSwipePolicy):
            message = "campaign map swipe policy source must provide MapSwipePolicy"
            raise CampaignRuntimeProfileError(message)
        policies.append(policy)

    if len(policies) > 1:
        message = "campaign map swipe service accepts at most one policy source"
        raise CampaignRuntimeProfileError(message)
    return MapSwipeService(policy=STANDARD_MAP_SWIPE_POLICY if not policies else policies[0])
