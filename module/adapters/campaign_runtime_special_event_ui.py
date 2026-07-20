from typing import TYPE_CHECKING, Protocol, cast, override

from module.base.timer import Timer
from module.base.utils import area_in_area, area_pad, crop, rgb2gray
from module.campaign.assets import (
    EVENT_20230817_STORY,
    TEMPLATE_EVENT_20230817_STORY_E1,
    TEMPLATE_EVENT_20230817_STORY_E2,
)
from module.combat.assets import GET_ITEMS_1
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId
from module.exception import CampaignNameError
from module.logger import logger
from module.ui.page import page_event

from .campaign_event_ui import (
    CampaignEventCombatResultContributor,
    CampaignEventStageRecoveryContributor,
    CampaignEventUiContributor,
    CampaignEventUiExecutor,
    CampaignMapTransitionContributor,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)

if TYPE_CHECKING:
    from module.base.button import Button
    from module.base.type_alias import ImageArray
    from module.campaign.campaign_engine import CampaignEngine
    from module.combat.combat_result_ui import CombatResultRuntime
    from module.handler.map_transition_ui import MapTransitionRuntime

    from .campaign_event_ui import EventCombatResultNext, EventStageRecoveryNext, MapTransitionNext


class _DevicePort(Protocol):
    image: ImageArray

    def screenshot(self) -> object: ...

    def click(self, button: object) -> object: ...


class _SpecialEventUiHost(Protocol):
    device: _DevicePort

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool: ...

    def ui_page_appear(self, page: object) -> bool: ...

    def handle_story_skip(self) -> bool: ...

    def handle_get_items(self) -> bool: ...

    def image_color_button(
        self,
        *,
        area: tuple[int, int, int, int],
        color: tuple[int, int, int],
        color_threshold: int,
        encourage: int,
        name: str,
    ) -> Button | None: ...

    def is_in_stage_page(self) -> bool: ...

    def try_update_stage_entrances(self, image: ImageArray) -> bool: ...

    def interval_clear(self, button: object) -> object: ...

    def appear_then_click(
        self,
        button: object,
        *,
        offset: tuple[int, int],
        interval: float,
    ) -> bool: ...


def _host(runtime: object) -> _SpecialEventUiHost:
    return cast("_SpecialEventUiHost", runtime)


class Event20230817UiExecutor(CampaignEventUiExecutor):
    """处理以剧情按钮代替关卡入口的活动页面。"""

    __slots__ = ()

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        context.options(RuntimeExecutorKind.EVENT_UI)
        super().__init__(
            {RuntimeExecutorKind.EVENT_UI},
            CampaignEventUiContributor(
                stage_recovery=CampaignEventStageRecoveryContributor(
                    recover_chapter_selection=self._recover_chapter_selection,
                ),
                map_transition=CampaignMapTransitionContributor(
                    stage_page_ready=self._stage_page_ready,
                ),
            ),
        )

    @staticmethod
    def _get_story_button(runtime: object) -> Button | None:
        host = _host(runtime)
        if host.appear(EVENT_20230817_STORY, offset=(20, 100)):
            return EVENT_20230817_STORY
        area = (73, 135, 1223, 583)
        image = rgb2gray(crop(host.device.image, area=area, copy=False))
        for template in (TEMPLATE_EVENT_20230817_STORY_E1, TEMPLATE_EVENT_20230817_STORY_E2):
            similarity, button = template.match_result(image)
            if similarity > 0.85:
                return button.move(area[:2])
        return None

    def _recover_chapter_selection(
        self,
        runtime: CampaignEngine,
        next_handler: EventStageRecoveryNext,
    ) -> bool:
        if self._get_story_button(runtime) is not None:
            self._run_story(runtime)
            return True
        logger.info("No event_20230817_story")
        return next_handler(runtime)

    def _run_story(self, runtime: object, *, skip_first_screenshot: bool = True) -> object:
        host = _host(runtime)
        logger.hr("event_20230817_story", level=2)
        confirm = Timer(1, count=3).start()
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                host.device.screenshot()
            if host.ui_page_appear(page_event):
                if confirm.reached():
                    return None
            else:
                confirm.reset()
            if host.handle_story_skip() or host.handle_get_items():
                continue
            button = self._get_story_button(runtime)
            if button is not None:
                host.device.click(button)

    def _stage_page_ready(self, runtime: MapTransitionRuntime, next_handler: MapTransitionNext) -> bool:
        if self._get_story_button(runtime) is not None:
            return True
        return next_handler(runtime)


class Event20240815UiExecutor(CampaignEventUiExecutor):
    """用实例内 timer 驱动剧情入口清理，避免跨 runtime 共享可变状态。"""

    __slots__ = ("_entrance_timer",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.EVENT_UI)
        if options["exp_info_blocked_page"] != "event":
            message = "event 20240815 EXP-info guard must target event page"
            raise CampaignRuntimeProfileError(message)
        state = options["state"]
        if state != ("entrance_timer",):
            message = "event 20240815 UI must own entrance_timer state"
            raise CampaignRuntimeProfileError(message)
        self._entrance_timer = Timer(2)
        super().__init__(
            {RuntimeExecutorKind.EVENT_UI},
            CampaignEventUiContributor(
                stage_recovery=CampaignEventStageRecoveryContributor(
                    recover_campaign_selection=self._recover_campaign_selection,
                    recover_stage_page=self._recover_stage_page,
                ),
                combat_result=CampaignEventCombatResultContributor(
                    handle_experience_result=self._handle_experience_result,
                ),
                map_transition=CampaignMapTransitionContributor(
                    handle_stage_return=self._handle_stage_return,
                ),
            ),
        )

    @staticmethod
    def _get_story_entrance(runtime: object) -> Button | None:
        host = _host(runtime)
        button = host.image_color_button(
            area=(66, 200, 1200, 690),
            color=(0, 0, 0),
            color_threshold=240,
            encourage=10,
            name="STORY_ENTRANCE",
        )
        if button is None:
            return None
        if area_in_area(button.button, area_pad((424, 522, 444, 542), pad=-20)):
            return None
        return button

    def _handle_story_entrance(self, runtime: object) -> object:
        if not self._entrance_timer.reached():
            return False
        entrance = self._get_story_entrance(runtime)
        if entrance is None:
            return False
        _host(runtime).device.click(entrance)
        self._entrance_timer.reset()
        return True

    def _ensure_no_stage_entrance(self, runtime: object, *, skip_first_screenshot: bool = True) -> object:
        host = _host(runtime)
        logger.info("ensure_no_stage_entrance")
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                host.device.screenshot()
            if host.is_in_stage_page():
                if host.try_update_stage_entrances(host.device.image):
                    return True
                if self._handle_story_entrance(runtime):
                    continue
            if host.handle_story_skip():
                host.interval_clear(GET_ITEMS_1)
                self._entrance_timer.clear()
                continue
            if host.appear_then_click(GET_ITEMS_1, offset=(20, 20), interval=3):
                self._entrance_timer.clear()

    def _handle_stage_return(self, runtime: MapTransitionRuntime, next_handler: MapTransitionNext) -> bool:
        host = _host(runtime)
        if host.is_in_stage_page() and self._handle_story_entrance(runtime):
            return False
        return next_handler(runtime)

    def _recover_stage_page(
        self,
        runtime: CampaignEngine,
        next_handler: EventStageRecoveryNext,
    ) -> bool:
        if self._get_story_entrance(runtime) is not None:
            raise CampaignNameError
        return next_handler(runtime)

    def _recover_campaign_selection(
        self,
        runtime: CampaignEngine,
        next_handler: EventStageRecoveryNext,
    ) -> bool:
        if self._get_story_entrance(runtime) is not None:
            self._ensure_no_stage_entrance(runtime)
            return True
        return next_handler(runtime)

    @staticmethod
    def _handle_experience_result(
        runtime: CombatResultRuntime,
        next_handler: EventCombatResultNext,
    ) -> bool:
        host = _host(runtime)
        if host.ui_page_appear(page_event):
            return False
        return next_handler(runtime)

    @override
    def reset(self) -> None:
        self._entrance_timer.clear()
        super().reset()


def _build_event_20230817_ui(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return Event20230817UiExecutor(context)


def _build_event_20240815_ui(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return Event20240815UiExecutor(context)


def special_event_ui_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    event_ui = RuntimeExecutorKind.EVENT_UI
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_20230817_cn/campaign_base/campaign_base"),
            {event_ui: RuntimeExecutorOptionsSchema()},
            _build_event_20230817_ui,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_20240815_cn/campaign_base/campaign_base"),
            {
                event_ui: RuntimeExecutorOptionsSchema(
                    required=frozenset({"exp_info_blocked_page", "state"}),
                )
            },
            _build_event_20240815_ui,
        ),
    )
