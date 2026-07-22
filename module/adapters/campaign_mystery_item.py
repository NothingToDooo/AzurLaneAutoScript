from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from module.content.runtime_profile import RuntimeExecutorKind
from module.handler.mystery_item import (
    STANDARD_MYSTERY_ITEM_SERVICE,
    MysteryItemOutcome,
    MysteryItemRequest,
    MysteryItemRuntime,
    MysteryItemService,
)

from .campaign_runtime_profile import CampaignRuntimeProfileError, RuntimeExecutorInstance

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

type MysteryItemNext = Callable[
    [MysteryItemRuntime, MysteryItemRequest],
    MysteryItemOutcome,
]
type MysteryItemHandler = Callable[
    [MysteryItemRuntime, MysteryItemRequest, MysteryItemNext],
    MysteryItemOutcome,
]


@dataclass(frozen=True, slots=True)
class CampaignMysteryItemContributor:
    handler: MysteryItemHandler

    def __post_init__(self) -> None:
        if not callable(self.handler):
            message = "campaign mystery item contributor requires a handler"
            raise TypeError(message)


@runtime_checkable
class CampaignMysteryItemContributorSource(Protocol):
    @property
    def mystery_item_contributor(self) -> CampaignMysteryItemContributor: ...


class CampaignMysteryItemExecutor(RuntimeExecutorInstance):
    __slots__ = ("_mystery_item_contributor",)

    def __init__(self, contributor: CampaignMysteryItemContributor) -> None:
        if not isinstance(contributor, CampaignMysteryItemContributor):
            message = "campaign mystery item executor requires a typed contributor"
            raise TypeError(message)
        super().__init__({RuntimeExecutorKind.MAP_MECHANIC})
        self._mystery_item_contributor = contributor

    @property
    def mystery_item_contributor(self) -> CampaignMysteryItemContributor:
        return self._mystery_item_contributor


@dataclass(frozen=True, slots=True)
class _ComposedMysteryItemService(MysteryItemService):
    handler: MysteryItemNext

    @override
    def handle(
        self,
        runtime: MysteryItemRuntime,
        request: MysteryItemRequest,
    ) -> MysteryItemOutcome:
        outcome = self.handler(runtime, request)
        if not isinstance(outcome, MysteryItemOutcome):
            message = "campaign mystery item handler must return MysteryItemOutcome"
            raise CampaignRuntimeProfileError(message)
        return outcome


def _overlay_mystery_item(
    handler: MysteryItemHandler,
    next_handler: MysteryItemNext,
) -> MysteryItemNext:
    def execute(
        runtime: MysteryItemRuntime,
        request: MysteryItemRequest,
    ) -> MysteryItemOutcome:
        return handler(runtime, request, next_handler)

    return execute


def build_campaign_mystery_item_service(
    instances: Iterable[object],
) -> MysteryItemService:
    """按 profile 顺序组合 mystery item 规则；后声明的 contributor 先处理。"""

    handler = STANDARD_MYSTERY_ITEM_SERVICE.handle
    for instance in instances:
        if not isinstance(instance, CampaignMysteryItemContributorSource):
            continue
        contributor = instance.mystery_item_contributor
        handler = _overlay_mystery_item(contributor.handler, handler)
    return _ComposedMysteryItemService(handler)
