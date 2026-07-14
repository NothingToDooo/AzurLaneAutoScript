from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast, override

from module.base.timer import Timer
from module.base.utils import area_in_area, area_pad, crop, rgb2gray
from module.campaign.assets import (
    EVENT_20230817_STORY,
    TEMPLATE_EVENT_20230817_STORY_E1,
    TEMPLATE_EVENT_20230817_STORY_E2,
)
from module.combat.assets import GET_ITEMS_1
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.exception import CampaignNameError
from module.logger import logger
from module.ui.page import page_event

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.base.button import Button
    from module.base.type_alias import ImageArray


class _DevicePort(Protocol):
    image: ImageArray

    def screenshot(self) -> object: ...

    def click(self, button: object) -> object: ...


class _SpecialEventUiHost(Protocol):
    device: _DevicePort

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...

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

    def _get_stage_name(self, image: ImageArray) -> object: ...

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


def _operations(options: Mapping[str, RuntimeTuningValue]) -> frozenset[str]:
    value = options["operations"]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = "dedicated event UI operations must contain strings"
        raise CampaignRuntimeProfileError(message)
    return frozenset(cast("tuple[str, ...]", value))


class Event20230817UiExecutor(RuntimeExecutorInstance):
    """处理以剧情按钮代替关卡入口的活动页面。"""

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.EVENT_UI)
        expected = {
            "event_20230817_story",
            "get_story_button",
            "handle_chapter_additional",
            "is_stage_page_has_entrance",
        }
        if _operations(options) != expected:
            message = "event 20230817 UI operations mismatch"
            raise CampaignRuntimeProfileError(message)
        super().__init__(
            {RuntimeExecutorKind.EVENT_UI},
            methods={
                RuntimeExecutorKind.EVENT_UI: {
                    RuntimeOperation.EVENT_20230817_STORY: self._run_story,
                    RuntimeOperation.GET_STORY_BUTTON: self._get_story_button_operation,
                    RuntimeOperation.HANDLE_CHAPTER_ADDITIONAL: self._handle_chapter_additional,
                    RuntimeOperation.IS_STAGE_PAGE_HAS_ENTRANCE: self._is_stage_page_has_entrance,
                }
            },
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

    def _get_story_button_operation(self, runtime: object) -> object:
        return self._get_story_button(runtime)

    def _handle_chapter_additional(self, runtime: object) -> object:
        if self._get_story_button(runtime) is not None:
            self._run_story(runtime)
            return True
        logger.info("No event_20230817_story")
        return False

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

    def _is_stage_page_has_entrance(self, runtime: object) -> object:
        if self._get_story_button(runtime) is not None:
            return True
        return _host(runtime).runtime_super(RuntimeOperation.IS_STAGE_PAGE_HAS_ENTRANCE)


class Event20240815UiExecutor(RuntimeExecutorInstance):
    """用实例内 timer 驱动剧情入口清理，避免跨 runtime 共享可变状态。"""

    __slots__ = ("_entrance_timer",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.EVENT_UI)
        expected = {
            "ensure_no_stage_entrance",
            "get_story_entrance",
            "handle_campaign_ui_additional",
            "handle_exp_info",
            "handle_get_chapter_additional",
            "handle_in_stage",
            "handle_story_entrance",
        }
        if _operations(options) != expected:
            message = "event 20240815 UI operations mismatch"
            raise CampaignRuntimeProfileError(message)
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
            methods={
                RuntimeExecutorKind.EVENT_UI: {
                    RuntimeOperation.ENSURE_NO_STAGE_ENTRANCE: self._ensure_no_stage_entrance,
                    RuntimeOperation.GET_STORY_ENTRANCE: self._get_story_entrance_operation,
                    RuntimeOperation.HANDLE_CAMPAIGN_UI_ADDITIONAL: self._handle_campaign_ui_additional,
                    RuntimeOperation.HANDLE_EXP_INFO: self._handle_exp_info,
                    RuntimeOperation.HANDLE_GET_CHAPTER_ADDITIONAL: self._handle_get_chapter_additional,
                    RuntimeOperation.HANDLE_IN_STAGE: self._handle_in_stage,
                    RuntimeOperation.HANDLE_STORY_ENTRANCE: self._handle_story_entrance,
                }
            },
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

    def _get_story_entrance_operation(self, runtime: object) -> object:
        return self._get_story_entrance(runtime)

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
                try:
                    # 旧 OCR 引擎只暴露此解析入口；私有访问被收敛在 production adapter 内。
                    host._get_stage_name(host.device.image)  # noqa: SLF001
                except IndexError, CampaignNameError:
                    if self._handle_story_entrance(runtime):
                        continue
                else:
                    return True
            if host.handle_story_skip():
                host.interval_clear(GET_ITEMS_1)
                self._entrance_timer.clear()
                continue
            if host.appear_then_click(GET_ITEMS_1, offset=(20, 20), interval=3):
                self._entrance_timer.clear()

    def _handle_in_stage(self, runtime: object) -> object:
        host = _host(runtime)
        if host.is_in_stage_page() and self._handle_story_entrance(runtime):
            return False
        return host.runtime_super(RuntimeOperation.HANDLE_IN_STAGE)

    def _handle_get_chapter_additional(self, runtime: object) -> object:
        if self._get_story_entrance(runtime) is not None:
            raise CampaignNameError
        return _host(runtime).runtime_super(RuntimeOperation.HANDLE_GET_CHAPTER_ADDITIONAL)

    def _handle_campaign_ui_additional(self, runtime: object) -> object:
        if self._get_story_entrance(runtime) is not None:
            self._ensure_no_stage_entrance(runtime)
            return True
        return _host(runtime).runtime_super(RuntimeOperation.HANDLE_CAMPAIGN_UI_ADDITIONAL)

    @staticmethod
    def _handle_exp_info(runtime: object) -> object:
        host = _host(runtime)
        if host.ui_page_appear(page_event):
            return False
        return host.runtime_super(RuntimeOperation.HANDLE_EXP_INFO)

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
            {
                event_ui: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations"}),
                )
            },
            _build_event_20230817_ui,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_20240815_cn/campaign_base/campaign_base"),
            {
                event_ui: RuntimeExecutorOptionsSchema(
                    required=frozenset({"exp_info_blocked_page", "operations", "state"}),
                )
            },
            _build_event_20240815_ui,
        ),
    )
