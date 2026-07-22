from module.combat.assets import GET_ITEMS_1_RYZA
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId
from module.handler.assets import MYSTERY_ITEM
from module.handler.mystery_item import MysteryItemOutcome, MysteryItemRequest, MysteryItemRuntime
from module.logger import logger

from .campaign_mystery_item import (
    CampaignMysteryItemContributor,
    CampaignMysteryItemExecutor,
    MysteryItemNext,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)


def _build_non_counting_mystery(
    context: RuntimeExecutorBuildContext,
) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
    if options["count_as_mystery"] is not False:
        message = "non-counting mystery executor requires count_as_mystery=false"
        raise CampaignRuntimeProfileError(message)

    def handle(
        runtime: MysteryItemRuntime,
        request: MysteryItemRequest,
        next_handler: MysteryItemNext,
    ) -> MysteryItemOutcome:
        outcome = next_handler(runtime, request)
        if not outcome.handled:
            return outcome
        return MysteryItemOutcome(handled=True, counts_toward_mystery=False)

    return CampaignMysteryItemExecutor(CampaignMysteryItemContributor(handle))


def _build_ryza_mystery(
    context: RuntimeExecutorBuildContext,
) -> RuntimeExecutorInstance:
    del context

    def handle(
        runtime: MysteryItemRuntime,
        request: MysteryItemRequest,
        next_handler: MysteryItemNext,
    ) -> MysteryItemOutcome:
        outcome = next_handler(runtime, request)
        if outcome.handled:
            return outcome
        if not runtime.appear(GET_ITEMS_1_RYZA, offset=(-20, -100, 20, 20)):
            return outcome
        logger.attr("Mystery", "Get item")
        runtime.device.click(MYSTERY_ITEM)
        runtime.device.sleep(0.5)
        runtime.device.screenshot()
        return MysteryItemOutcome(handled=True, counts_toward_mystery=True)

    return CampaignMysteryItemExecutor(CampaignMysteryItemContributor(handle))


def mystery_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    mechanic = RuntimeExecutorKind.MAP_MECHANIC
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/non_counting_mystery_popup"),
            {
                mechanic: RuntimeExecutorOptionsSchema(
                    required=frozenset({"count_as_mystery"}),
                )
            },
            _build_non_counting_mystery,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/ryza_mystery_items"),
            {mechanic: RuntimeExecutorOptionsSchema()},
            _build_ryza_mystery,
        ),
    )
