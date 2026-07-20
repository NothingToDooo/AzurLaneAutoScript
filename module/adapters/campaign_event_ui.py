from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from module.campaign.event_destination import STANDARD_EVENT_DESTINATION, EventDestination
from module.content.errors import ContentValidationError
from module.content.runtime_profile import RuntimeExecutorKind

from .campaign_runtime_profile import RuntimeExecutorInstance, RuntimeMethod, RuntimeOperation

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class CampaignEventUiContributor:
    """一个 runtime executor 对活动 UI typed services 的贡献。"""

    destination: EventDestination | None = None


@runtime_checkable
class CampaignEventUiContributorSource(Protocol):
    @property
    def event_ui_contributor(self) -> CampaignEventUiContributor: ...


class CampaignEventUiExecutor(RuntimeExecutorInstance):
    """同时提供 operation facet 与 typed event UI 能力的专用 executor。"""

    __slots__ = ("_event_ui_contributor",)

    def __init__(
        self,
        supported_kinds: Iterable[RuntimeExecutorKind],
        contributor: CampaignEventUiContributor,
        *,
        methods: Mapping[RuntimeExecutorKind, Mapping[RuntimeOperation, RuntimeMethod]] | None = None,
    ) -> None:
        kinds = frozenset(supported_kinds)
        if RuntimeExecutorKind.EVENT_UI not in kinds:
            message = "campaign event UI executor requires the event_ui kind"
            raise ContentValidationError(message)
        if not isinstance(contributor, CampaignEventUiContributor):
            message = "campaign event UI executor requires a typed contributor"
            raise TypeError(message)
        super().__init__(kinds, methods=methods)
        self._event_ui_contributor = contributor

    @property
    def event_ui_contributor(self) -> CampaignEventUiContributor:
        return self._event_ui_contributor


@dataclass(frozen=True, slots=True)
class CampaignEventUiServices:
    """每个 runtime 只编译一次的活动 UI 能力集合。"""

    destination: EventDestination


def build_campaign_event_ui_services(
    instances: Iterable[object],
) -> CampaignEventUiServices:
    """按 profile 声明顺序组合能力；同一职责由最后一个声明覆盖。"""

    destination = STANDARD_EVENT_DESTINATION
    for instance in instances:
        if not isinstance(instance, CampaignEventUiContributorSource):
            continue
        contributor = instance.event_ui_contributor
        if contributor.destination is not None:
            destination = contributor.destination
    return CampaignEventUiServices(destination=destination)
