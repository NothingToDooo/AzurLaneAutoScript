from collections.abc import Mapping
from typing import TYPE_CHECKING, cast, override

from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.exception import HumanTakeoverRequiredError
from module.logger import logger
from module.ui.assets import WAR_ARCHIVES_CHECK
from module.ui.page import page_archives
from module.ui.scroll import Scroll
from module.ui.switch import Switch
from module.war_archives.assets import (
    WAR_ARCHIVES_CAMPAIGN_CHECK,
    WAR_ARCHIVES_EX_ON,
    WAR_ARCHIVES_SCROLL,
    WAR_ARCHIVES_SP_ON,
)
from module.war_archives.profile import (
    WAR_ARCHIVES_CLIENT_PROFILES,
    WarArchivesClientProfile,
    WarArchivesClientProfileError,
)

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
)

if TYPE_CHECKING:
    from typing import Protocol

    from module.base.button import Button
    from module.campaign.campaign_engine import CampaignEngine
    from module.content.stage_definition import CampaignStageDefinition

    class WarArchivesRuntimeHost(Protocol):
        definition: CampaignStageDefinition


_ARCHIVES_SWITCH = Switch("War_Archives_switch", is_selector=True)
_ARCHIVES_SWITCH.add_state("ex", WAR_ARCHIVES_EX_ON)
_ARCHIVES_SWITCH.add_state("sp", WAR_ARCHIVES_SP_ON)
_ARCHIVES_SCROLL = Scroll(WAR_ARCHIVES_SCROLL, color=(247, 211, 66), name="WAR_ARCHIVES_SCROLL")

_PUBLIC_OPERATIONS = frozenset(
    {
        "ui_goto_archives_campaign",
        "ui_goto_event",
        "ui_goto_sp",
    }
)
_INTERNAL_OPERATIONS = frozenset(
    {
        "_advance_archives_scroll",
        "_archives_loading_complete",
        "_discard_archives_scroll_record",
        "_ensure_archives_search_page",
        "_get_archives_entrance",
        "_search_archives_entrance",
        "_wait_archives_loaded",
    }
)


def _tuple_of_strings(options: Mapping[str, RuntimeTuningValue], name: str) -> tuple[str, ...]:
    value = options[name]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = f"war-archives option {name} must contain strings"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[str, ...]", value)


def _positive_integer(options: Mapping[str, RuntimeTuningValue], name: str) -> int:
    value = options[name]
    if type(value) is not int or value <= 0:
        message = f"war-archives option {name} must be a positive integer"
        raise CampaignRuntimeProfileError(message)
    return value


def _fraction(options: Mapping[str, RuntimeTuningValue], name: str) -> float:
    value = options[name]
    if type(value) not in (int, float):
        message = f"war-archives option {name} must be a number"
        raise CampaignRuntimeProfileError(message)
    fraction = float(cast("int | float", value))
    if not 0 < fraction <= 1:
        message = f"war-archives option {name} must be in (0, 1]"
        raise CampaignRuntimeProfileError(message)
    return fraction


class WarArchivesCatalogExecutor(RuntimeExecutorInstance):
    """档案目录的有界滚动搜索与 EX/SP 入口状态机。"""

    __slots__ = (
        "_event_mode",
        "_first_run",
        "_match_threshold",
        "_max_search_attempts",
        "_page_fraction",
        "_sp_mode",
    )

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.WAR_ARCHIVES_NAVIGATION)
        operations = frozenset(_tuple_of_strings(options, "operations"))
        unknown_operations = sorted(operations - _PUBLIC_OPERATIONS - _INTERNAL_OPERATIONS)
        if unknown_operations:
            message = f"unsupported war-archives operation: {unknown_operations[0]}"
            raise CampaignRuntimeProfileError(message)
        missing_operations = sorted(_PUBLIC_OPERATIONS - operations)
        if missing_operations:
            message = f"war-archives catalog is missing operation: {missing_operations[0]}"
            raise CampaignRuntimeProfileError(message)
        state = _tuple_of_strings(options, "state")
        if state != ("first_run",):
            message = "war-archives catalog state must be ['first_run']"
            raise CampaignRuntimeProfileError(message)
        self._max_search_attempts = _positive_integer(options, "max_search_attempts")
        self._page_fraction = _fraction(options, "page_fraction")
        self._match_threshold = _fraction(options, "match_threshold")
        raw_modes = options["modes"]
        if not isinstance(raw_modes, Mapping):
            message = "war-archives modes must be an object"
            raise CampaignRuntimeProfileError(message)
        modes = cast("Mapping[str, RuntimeTuningValue]", raw_modes)
        self._event_mode = self._mode(modes, "event")
        self._sp_mode = self._mode(modes, "sp")
        self._first_run = True
        super().__init__(
            {RuntimeExecutorKind.WAR_ARCHIVES_NAVIGATION},
            methods={
                RuntimeExecutorKind.WAR_ARCHIVES_NAVIGATION: {
                    RuntimeOperation.UI_GOTO_ARCHIVES_CAMPAIGN: self._ui_goto_archives_campaign,
                    RuntimeOperation.UI_GOTO_EVENT: self._ui_goto_event,
                    RuntimeOperation.UI_GOTO_SP: self._ui_goto_sp,
                }
            },
        )

    @staticmethod
    def _mode(modes: Mapping[str, RuntimeTuningValue], name: str) -> str:
        value = modes.get(name)
        if value not in {"ex", "sp"}:
            message = f"war-archives mode {name} must be 'ex' or 'sp'"
            raise CampaignRuntimeProfileError(message)
        return cast("str", value)

    @override
    def reset(self) -> None:
        super().reset()
        self._first_run = True

    @staticmethod
    def _client_profile(runtime: CampaignEngine) -> WarArchivesClientProfile:
        definition = cast("WarArchivesRuntimeHost", runtime).definition.war_archives
        if definition is None:
            message = "war-archives runtime requires a typed client profile"
            raise CampaignRuntimeProfileError(message)
        try:
            return WAR_ARCHIVES_CLIENT_PROFILES.resolve(definition.profile_id)
        except WarArchivesClientProfileError as error:
            raise CampaignRuntimeProfileError(str(error)) from error

    def _get_archives_entrance(self, runtime: CampaignEngine) -> Button | None:
        profile = self._client_profile(runtime)
        similarity, button = profile.entrance.match_result(runtime.device.image)
        if similarity < self._match_threshold:
            return None
        return button.crop(
            (-12, -12, 44, 32),
            image=runtime.device.image,
            name=profile.profile_id.value,
        )

    @staticmethod
    def _archives_loading_complete(runtime: CampaignEngine) -> bool:
        return any(profile.entrance.match(runtime.device.image) for profile in WAR_ARCHIVES_CLIENT_PROFILES.profiles)

    @staticmethod
    def _discard_archives_scroll_record(runtime: CampaignEngine) -> None:
        while runtime.device.click_record and runtime.device.click_record[-1] == "WAR_ARCHIVES_SCROLL":
            runtime.device.click_record.pop()

    @staticmethod
    def _ensure_archives_search_page(runtime: CampaignEngine) -> bool:
        recovered = False
        while not runtime.appear(WAR_ARCHIVES_CHECK):
            runtime.ui_ensure(destination=page_archives)
            recovered = True
        return recovered

    def _wait_archives_loaded(self, runtime: CampaignEngine) -> None:
        while not self._archives_loading_complete(runtime):
            runtime.device.screenshot()

    def _advance_archives_scroll(self, runtime: CampaignEngine) -> bool:
        if not _ARCHIVES_SCROLL.appear(main=runtime):
            return False
        if _ARCHIVES_SCROLL.at_bottom(main=runtime):
            _ARCHIVES_SCROLL.set_top(main=runtime)
        else:
            _ARCHIVES_SCROLL.next_page(main=runtime, page=self._page_fraction)
        return True

    def _search_archives_entrance(
        self,
        runtime: CampaignEngine,
        *,
        skip_first_screenshot: bool = True,
    ) -> Button | None:
        loading_checked = False
        for _ in range(self._max_search_attempts):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                runtime.device.screenshot()
            self._discard_archives_scroll_record(runtime)
            if self._ensure_archives_search_page(runtime):
                loading_checked = False

            entrance = self._get_archives_entrance(runtime)
            if entrance is not None:
                return entrance
            if not loading_checked:
                self._wait_archives_loaded(runtime)
                loading_checked = True
                entrance = self._get_archives_entrance(runtime)
                if entrance is not None:
                    return entrance
            if not self._advance_archives_scroll(runtime):
                break
        logger.warning("Failed to find archives entrance")
        return None

    def _ui_goto_archives_campaign(self, runtime: object, mode: object = "ex") -> object:
        host = cast("CampaignEngine", runtime)
        if not isinstance(mode, str) or mode not in {"ex", "sp"}:
            message = "war-archives navigation mode must be 'ex' or 'sp'"
            raise CampaignRuntimeProfileError(message)
        result = True
        if self._first_run or not host.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
            result = host.ui_ensure(destination=page_archives)
            _ARCHIVES_SWITCH.set(mode, main=host)
            entrance = self._search_archives_entrance(host)
            if entrance is None:
                logger.critical(
                    "Respective server may not yet support the chosen War Archives campaign, "
                    "check back in the next app update"
                )
                raise HumanTakeoverRequiredError
            host.ui_click(
                entrance,
                appear_button=WAR_ARCHIVES_CHECK,
                check_button=WAR_ARCHIVES_CAMPAIGN_CHECK,
                skip_first_screenshot=True,
            )
        self._first_run = False
        return result

    def _ui_goto_event(self, runtime: object) -> object:
        return self._ui_goto_archives_campaign(runtime, self._event_mode)

    def _ui_goto_sp(self, runtime: object) -> object:
        return self._ui_goto_archives_campaign(runtime, self._sp_mode)


def _build_war_archives_catalog(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return WarArchivesCatalogExecutor(context)


def war_archives_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("navigation/war_archives_catalog"),
            {
                RuntimeExecutorKind.WAR_ARCHIVES_NAVIGATION: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "operations",
                            "state",
                            "max_search_attempts",
                            "page_fraction",
                            "match_threshold",
                            "modes",
                        }
                    )
                )
            },
            _build_war_archives_catalog,
        ),
    )
