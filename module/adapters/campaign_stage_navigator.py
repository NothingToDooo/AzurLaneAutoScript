from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.base.utils import area_offset, get_color
from module.campaign import assets as campaign_assets
from module.campaign.campaign_engine import CampaignEngine
from module.campaign.campaign_ui import (
    ASIDE_SWITCH_20241219,
    CAMPAIGN_NAME_ERROR_MESSAGE,
    CHAPTER_SWITCH_20241219_ASIDE,
    CHAPTER_SWITCH_20241219_SP_ASIDE,
    CHAPTER_SWITCH_20241219_SPEX_ASIDE,
    EVENT_CHAPTERS,
    EX_EVENT_CHAPTERS,
    HARD_EVENT_CHAPTERS,
    NORMAL_EVENT_CHAPTERS,
    CampaignStageNavigator,
    is_digit_chapter,
)
from module.content.runtime_profile import RuntimeExecutorKind
from module.exception import CampaignNameError, CampaignSelectionError
from module.logger import logger

from .campaign_runtime_navigation import (
    BallChapterNavigationPlan,
    CampaignBallOperation,
    CampaignModePolicyKind,
    CampaignNavigationPlan,
    CampaignNavigationPlanExecutor,
    CampaignRoute,
    CampaignRouteDestination,
    CampaignRouteMode,
    CampaignRouteTarget,
    ChapterRouteNavigationPlan,
    Event20240912NavigationPlan,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
)
from .campaign_runtime_war_archives import WarArchivesCatalogExecutor

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.adapters.campaign_event_ui import CampaignEventUiServices
    from module.base.button import Button
    from module.campaign.campaign_ocr import CampaignStagePage


class ProfileCampaignStageNavigator(CampaignStageNavigator):
    """把一个 runtime profile 编译结果收口成单一关卡选择接口。"""

    __slots__ = ("_archives", "_event_ui", "_page", "_plan", "_runtime")

    def __init__(
        self,
        runtime: CampaignEngine,
        event_ui: CampaignEventUiServices,
        plan: CampaignNavigationPlan | None,
        archives: WarArchivesCatalogExecutor | None,
    ) -> None:
        self._runtime = runtime
        self._event_ui = event_ui
        self._plan = plan
        self._archives = archives
        self._page: CampaignStagePage | None = None

    def select(
        self,
        name: str,
        mode: str = "normal",
        *,
        skip_first_screenshot: bool = True,
    ) -> Button:
        timeout = Timer(5, count=20).start()
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self._runtime.device.screenshot()

            if timeout.reached():
                break
            try:
                self._page = None
                self._select_chapter(name, mode)
                return self._resolve_entrance(name)
            except CampaignNameError:
                pass

            if self._handle_campaign_ui_additional():
                continue

        logger.warning(CAMPAIGN_NAME_ERROR_MESSAGE)
        raise CampaignSelectionError(CAMPAIGN_NAME_ERROR_MESSAGE)

    def _handle_campaign_ui_additional(self) -> bool:
        return self._runtime.handle_campaign_ui_additional()

    def _select_chapter(self, name: str, mode: str) -> None:
        chapter, stage = self._separate_name(name)
        plan = self._plan
        if isinstance(plan, BallChapterNavigationPlan):
            selected = self._select_ball_chapter(plan, chapter, stage, mode) or self._select_base_chapter(
                chapter,
                stage,
                mode,
                warn=False,
            )
        elif isinstance(plan, Event20240912NavigationPlan):
            selected = self._select_event_20240912(chapter, stage, mode)
        elif isinstance(plan, ChapterRouteNavigationPlan):
            selected = self._select_typed_route(plan, chapter, stage, mode)
        else:
            selected = self._select_base_chapter(chapter, stage, mode, warn=False)
        if not selected:
            self._unknown_chapter(name)

    def _select_event_20240912(self, chapter: str, stage: str, mode: str) -> bool:
        if self._select_main_chapter(chapter, mode):
            return True
        self._disable_20241219_navigation()
        return (
            self._select_base_20241219(chapter, stage, mode)
            or self._select_event_chapter(chapter)
            or self._select_sp_chapter(chapter)
        )

    def _select_typed_route(
        self,
        plan: ChapterRouteNavigationPlan,
        chapter: str,
        stage: str,
        mode: str,
    ) -> bool:
        target = plan.route_target
        if target is CampaignRouteTarget.ALL:
            return self._apply_first_route(plan.routes, chapter, stage, mode) or self._select_base_chapter(
                chapter,
                stage,
                mode,
                warn=False,
            )
        selected = self._select_main_chapter(chapter, mode)
        if not selected:
            selected = (
                self._apply_first_route(plan.routes, chapter, stage, mode)
                if target is CampaignRouteTarget.SWITCH_20241219
                else self._select_base_20241219(chapter, stage, mode)
            )
        if not selected:
            selected = (
                self._apply_first_route(plan.routes, chapter, stage, mode)
                if target is CampaignRouteTarget.EVENT
                else self._select_event_chapter(chapter)
            )
        if not selected:
            selected = (
                self._apply_first_route(plan.routes, chapter, stage, mode)
                if target is CampaignRouteTarget.SP
                else self._select_sp_chapter(chapter)
            )
        return selected

    def _select_base_chapter(
        self,
        chapter: str,
        stage: str,
        mode: str,
        *,
        warn: bool = True,
    ) -> bool:
        selected = (
            self._select_main_chapter(chapter, mode)
            or self._select_base_20241219(chapter, stage, mode)
            or self._select_event_chapter(chapter)
            or self._select_sp_chapter(chapter)
        )
        if not selected and warn:
            self._unknown_chapter(f"{chapter}{stage}")
        return selected

    @staticmethod
    def _unknown_chapter(name: str) -> None:
        logger.warning(f"Unknown campaign chapter: {name}")

    def _select_main_chapter(self, chapter: str, mode: str) -> bool:
        if not chapter.isdigit():
            return False
        self._open_campaign()
        self._ensure_mode("normal")
        self._ensure_chapter(chapter)
        if mode == "hard":
            self._ensure_mode("hard")
            self._runtime.handle_info_bar()
            self._ensure_chapter(chapter)
        return True

    def _select_event_chapter(self, chapter: str) -> bool:
        if chapter not in EVENT_CHAPTERS:
            return False
        self._open_event()
        if chapter in NORMAL_EVENT_CHAPTERS:
            self._ensure_mode("normal")
        elif chapter in HARD_EVENT_CHAPTERS:
            self._ensure_mode("hard")
        elif chapter in EX_EVENT_CHAPTERS:
            self._ensure_mode("ex")
        self._ensure_chapter(chapter)
        return True

    def _select_sp_chapter(self, chapter: str) -> bool:
        if chapter != "sp":
            return False
        self._open_sp()
        self._ensure_chapter(chapter)
        return True

    def _select_base_20241219(self, chapter: str, stage: str, mode: str) -> bool:
        config = self._runtime.config
        if config.MAP_CHAPTER_SWITCH_20241219:
            self._set_hard_mode(chapter, stage)
            if mode == "story":
                CampaignEngine.campaign_ensure_mode_20241219(self._runtime, "story")
                return True
            if self._select_20241219_aside(chapter, CHAPTER_SWITCH_20241219_ASIDE):
                return True
        if config.MAP_CHAPTER_SWITCH_20241219_SP:
            self._set_hard_mode(chapter, stage)
            if self._select_20241219_aside(chapter, CHAPTER_SWITCH_20241219_SP_ASIDE):
                return True
        if config.MAP_CHAPTER_SWITCH_20241219_SPEX:
            self._set_hard_mode(chapter, stage)
            try:
                ASIDE_SWITCH_20241219.offset = area_offset((-20, -20, 20, 20), (0, -37))
                if self._select_20241219_aside(chapter, CHAPTER_SWITCH_20241219_SPEX_ASIDE):
                    return True
            finally:
                ASIDE_SWITCH_20241219.offset = (20, 20)
        return False

    def _select_20241219_aside(self, chapter: str, aside_by_chapter: Mapping[str, str]) -> bool:
        aside = aside_by_chapter.get(chapter)
        if aside is None:
            return False
        self._open_event()
        CampaignEngine.campaign_ensure_mode_20241219(self._runtime, "combat")
        CampaignEngine.campaign_ensure_aside_20241219(self._runtime, aside)
        self._ensure_chapter(chapter)
        return True

    def _set_hard_mode(self, chapter: str, stage: str) -> None:
        name = f"{chapter}{stage}"
        mode_names = CampaignEngine.campaign_get_mode_names(name)
        if len(mode_names) == 2 and mode_names[1] == name:
            self._runtime.config.apply_runtime_overlay(Campaign_Mode="hard")

    def _disable_20241219_navigation(self) -> None:
        self._runtime.config.apply_runtime_overlay(
            MAP_CHAPTER_SWITCH_20241219=False,
            MAP_HAS_MODE_SWITCH=False,
        )

    def _apply_first_route(
        self,
        routes: tuple[CampaignRoute, ...],
        chapter: str,
        stage: str,
        requested_mode: str,
    ) -> bool:
        for route in routes:
            if self._route_matches(route, chapter):
                self._apply_route(route, chapter, stage, requested_mode)
                return True
        return False

    def _route_matches(self, route: CampaignRoute, chapter: str) -> bool:
        if route.requires_chapter_switch and not self._runtime.config.MAP_CHAPTER_SWITCH_20241219:
            return False
        return (
            route.match_all
            or (route.match_numeric and chapter.isdigit())
            or (route.chapters is not None and chapter in route.chapters)
            or (route.prefix is not None and chapter.startswith(route.prefix))
        )

    def _apply_route(
        self,
        route: CampaignRoute,
        chapter: str,
        stage: str,
        requested_mode: str,
    ) -> None:
        if route.destination is CampaignRouteDestination.CAMPAIGN:
            self._apply_campaign_route(route, chapter, requested_mode)
            return
        self._apply_event_route(route, chapter, stage, requested_mode)

    def _apply_campaign_route(
        self,
        route: CampaignRoute,
        chapter: str,
        requested_mode: str,
    ) -> None:
        self._open_campaign()
        self._ensure_mode("normal")
        self._ensure_chapter(chapter)
        selected_mode = requested_mode if route.mode is CampaignRouteMode.REQUESTED else route.mode.value
        if selected_mode != "hard":
            return
        self._ensure_mode("hard")
        if route.reselect_after_hard:
            self._runtime.handle_info_bar()
            self._ensure_chapter(chapter)

    def _apply_event_route(
        self,
        route: CampaignRoute,
        chapter: str,
        stage: str,
        requested_mode: str,
    ) -> None:
        if route.destination is CampaignRouteDestination.EVENT:
            self._open_event()
        else:
            self._open_sp()
        if route.hard_if_campaign_name_is_hard:
            self._set_hard_mode(chapter, stage)
        if route.mode in {CampaignRouteMode.NORMAL, CampaignRouteMode.HARD, CampaignRouteMode.EX}:
            self._ensure_mode(route.mode.value)
        elif route.mode is CampaignRouteMode.REQUESTED:
            self._ensure_mode(requested_mode)
        elif route.mode is CampaignRouteMode.COMBAT:
            CampaignEngine.campaign_ensure_mode_20241219(self._runtime, "combat")
        aside = route.aside
        for stages, candidate in route.aside_by_stage:
            if stage in stages:
                aside = candidate
                break
        if aside is not None:
            CampaignEngine.campaign_ensure_aside_20241219(self._runtime, aside)
        self._ensure_chapter(chapter)

    def _select_ball_chapter(
        self,
        plan: BallChapterNavigationPlan,
        chapter: str,
        stage: str,
        mode: str,
    ) -> bool:
        if self._select_ball_main_chapter(chapter, mode):
            return True
        event_mode = plan.event_modes.get(chapter)
        if event_mode is not None:
            self._open_event()
            self._ensure_mode(event_mode)
            self._ensure_chapter(chapter)
            return True
        if chapter == "sp":
            if plan.sp_destination is CampaignRouteDestination.EVENT:
                self._open_event()
            else:
                self._open_sp()
            self._ensure_chapter("sp")
            return True
        if chapter not in plan.ball_chapters:
            return False
        self._open_event()
        for operation in plan.operation_order:
            if operation is CampaignBallOperation.SET_BALL:
                self._set_ball(plan, self._ball_status(plan, chapter, stage))
            else:
                self._ensure_ball_mode(plan, chapter)
        self._ensure_chapter(1)
        return True

    def _select_ball_main_chapter(self, chapter: str, mode: str) -> bool:
        if not chapter.isdigit():
            return False
        self._open_campaign()
        self._ensure_mode("normal")
        self._ensure_chapter(chapter)
        if mode == "hard":
            self._ensure_mode("hard")
        return True

    @staticmethod
    def _ball_status(plan: BallChapterNavigationPlan, chapter: str, stage: str) -> str:
        for rule in plan.blue_rules:
            if rule.chapters is not None and chapter not in rule.chapters:
                continue
            if stage in rule.stages:
                return "blue"
        return "red"

    def _ensure_ball_mode(self, plan: BallChapterNavigationPlan, chapter: str) -> None:
        if chapter in plan.normal_chapters:
            self._ensure_mode("normal")
            return
        if chapter in plan.hard_chapters:
            self._ensure_mode("hard")
            return
        message = f"unsupported campaign ball chapter: {chapter}"
        raise CampaignRuntimeProfileError(message)

    def _get_ball(self, plan: BallChapterNavigationPlan) -> str:
        color = get_color(self._runtime.device.image, plan.ball.area)
        index = max(range(len(color)), key=lambda item: color[item])
        return plan.detected_colors.get(str(index), "unknown")

    def _set_ball(self, plan: BallChapterNavigationPlan, status: str) -> None:
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self._runtime.device.screenshot()
            if self._get_ball(plan) == status:
                return
            if self._runtime.is_in_stage():
                self._runtime.device.click(plan.ball)
                self._runtime.device.sleep(plan.click_wait_seconds)
                while True:
                    self._runtime.device.screenshot()
                    if self._runtime.is_in_stage():
                        break

    def _ensure_mode(self, mode: str) -> None:
        plan = self._plan
        if isinstance(plan, Event20240912NavigationPlan):
            if mode == "story":
                plan.mode_switch.set("story", main=self._runtime)
            elif mode in {"normal", "hard", "ex"}:
                plan.mode_switch.set("combat", main=self._runtime)
                CampaignEngine.campaign_ensure_mode(self._runtime, mode)
            return
        if not isinstance(plan, ChapterRouteNavigationPlan):
            CampaignEngine.campaign_ensure_mode(self._runtime, mode)
            return
        policy = plan.mode_policy
        if policy.kind is CampaignModePolicyKind.NOOP:
            return
        if policy.kind is CampaignModePolicyKind.INHERITED:
            CampaignEngine.campaign_ensure_mode(self._runtime, mode)
            return
        if mode == "hard" and policy.hard_config_override:
            self._runtime.config.apply_runtime_overlay(Campaign_Mode="hard")
        if policy.kind is CampaignModePolicyKind.BRIDGE_20241219:
            CampaignEngine.campaign_ensure_mode_20241219(self._runtime, mode)

    def _ensure_chapter(self, chapter: str | int, *, skip_first_screenshot: bool = True) -> None:
        index = self._chapter_index(chapter)
        target_is_digit = is_digit_chapter(chapter)
        logger.hr("UI ensure index")
        retry = Timer(1, count=2)
        error_confirm = Timer(0.2, count=0)
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self._runtime.device.screenshot()
            if self._runtime.handle_chapter_additional():
                continue
            page = self._current_page()
            current = self._chapter_index(page.chapter)
            logger.attr("Index", current)
            diff = index - current
            if diff == 0:
                return
            if target_is_digit != is_digit_chapter(page.chapter):
                continue
            if index >= 11 and index % 10 == current:
                error_confirm.start()
                if not error_confirm.reached():
                    continue
            else:
                error_confirm.reset()
            if retry.reached():
                button = campaign_assets.CHAPTER_NEXT if diff > 0 else campaign_assets.CHAPTER_PREV
                self._runtime.device.multi_click(button, n=abs(diff), interval=(0.2, 0.3))
                retry.reset()

    def _current_page(self, *, skip_first_screenshot: bool = True) -> CampaignStagePage:
        timeout = Timer(2, count=4).start()
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self._runtime.device.screenshot()
            if timeout.reached():
                raise CampaignNameError
            try:
                page = CampaignEngine.read_stage_page(
                    self._runtime,
                    self._runtime.device.image,
                    normalize_result=self._normalize_ocr,
                    separate_name=self._separate_name,
                    match_similarity=self._match_similarity,
                )
            except IndexError, CampaignNameError:
                if self._runtime.handle_get_chapter_additional():
                    continue
            else:
                self._page = page
                return page

    @property
    def _match_similarity(self) -> float | None:
        plan = self._plan
        return plan.stage_match_similarity if isinstance(plan, ChapterRouteNavigationPlan) else None

    def _chapter_index(self, name: str | int) -> int:
        if isinstance(name, int):
            return name
        if name.isdigit():
            return int(name)
        plan = self._plan
        if isinstance(plan, (ChapterRouteNavigationPlan, BallChapterNavigationPlan)):
            index = plan.chapter_indices.get(name)
            if index is not None:
                return index
        return CampaignEngine.campaign_get_chapter_index(name)

    def _normalize_ocr(self, result: str) -> str:
        normalized = CampaignEngine.campaign_ocr_result_process(result)
        plan = self._plan
        if isinstance(plan, ChapterRouteNavigationPlan):
            return plan.ocr_aliases.get(normalized, normalized)
        return normalized

    def _separate_name(self, name: str) -> tuple[str, str]:
        plan = self._plan
        if isinstance(plan, ChapterRouteNavigationPlan):
            for rule in plan.name_rules:
                separated = rule.separate(name)
                if separated is not None:
                    return separated
        return CampaignEngine.campaign_separate_name(name)

    def _resolve_entrance(self, name: str) -> Button:
        page = self._page
        if page is None:
            raise CampaignNameError
        selected = name
        plan = self._plan
        if isinstance(plan, ChapterRouteNavigationPlan):
            selected = plan.entrance_aliases.get(name, name)
            search = plan.entrance_search
            if search is not None and name == search.input_name:
                for stage_name in page.entrances:
                    if search.contains in stage_name.lower():
                        selected = stage_name
        entrance_name = selected
        if self._runtime.config.MAP_HAS_MODE_SWITCH:
            for mode_name in CampaignEngine.campaign_get_mode_names(selected):
                if mode_name in page.entrances:
                    selected = mode_name
        try:
            entrance = page.entrances[selected]
        except KeyError:
            logger.warning(f"Stage not found: {selected}")
            raise CampaignNameError from None
        entrance.name = entrance_name
        return entrance

    def _open_event(self) -> bool:
        if self._archives is not None:
            return self._archives.open_event(self._runtime)
        return self._event_ui.destination.open(self._runtime)

    def _open_campaign(self) -> bool:
        return bool(CampaignEngine.ui_goto_campaign(self._runtime))

    def _open_sp(self) -> bool:
        if self._archives is not None:
            return self._archives.open_sp(self._runtime)
        return bool(CampaignEngine.ui_goto_sp(self._runtime))


def build_campaign_stage_navigator(
    runtime: CampaignEngine,
    manager: CampaignRuntimeProfileManager,
    event_ui: CampaignEventUiServices,
) -> ProfileCampaignStageNavigator:
    navigation = manager.executor_instance(RuntimeExecutorKind.NAVIGATION)
    if navigation is not None and not isinstance(navigation, CampaignNavigationPlanExecutor):
        message = "runtime navigation executor did not compile a typed plan"
        raise CampaignRuntimeProfileError(message)
    archives = manager.executor_instance(RuntimeExecutorKind.WAR_ARCHIVES_NAVIGATION)
    if archives is not None and not isinstance(archives, WarArchivesCatalogExecutor):
        message = "runtime war-archives executor did not compile a typed catalog"
        raise CampaignRuntimeProfileError(message)
    plan = None if navigation is None else navigation.plan
    return ProfileCampaignStageNavigator(
        runtime,
        event_ui,
        plan,
        archives,
    )
