from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, cast

from module.base.button import Button
from module.base.utils import get_color
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
)

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray

_DREAMWAKER_BALL = Button(
    area=(571, 283, 696, 387),
    color=(),
    button=(597, 274, 671, 343),
    name="DREAMWAKER_BALL",
)
_CONFLUENCE_BALL = Button(
    area=(589, 279, 685, 374),
    color=(),
    button=(589, 279, 685, 374),
    name="CONFLUENCE_BALL",
)
_BALL_ASSETS = {
    "DREAMWAKER_BALL": _DREAMWAKER_BALL,
    "CONFLUENCE_BALL": _CONFLUENCE_BALL,
}

_ROUTE_OPERATIONS = frozenset(
    {
        "campaign_ensure_mode",
        "campaign_get_chapter_index",
        "campaign_get_entrance",
        "campaign_match_multi",
        "campaign_ocr_result_process",
        "campaign_separate_name",
        "campaign_set_chapter",
        "campaign_set_chapter_20241219",
        "campaign_set_chapter_event",
        "campaign_set_chapter_sp",
    }
)
_BALL_OPERATIONS = frozenset(
    {
        "_campaign_ball_get",
        "_campaign_ball_set",
        "_campaign_ball_status",
        "_campaign_ensure_ball_mode",
        "campaign_get_chapter_index",
        "campaign_set_chapter",
        "campaign_set_chapter_ball",
        "campaign_set_chapter_event",
        "campaign_set_chapter_main",
        "campaign_set_chapter_sp",
    }
)


class _NavigationConfig(Protocol):
    MAP_CHAPTER_SWITCH_20241219: bool

    def apply_runtime_overlay(self, **kwargs: object) -> None: ...


class _NavigationDevice(Protocol):
    image: ImageArray

    def screenshot(self) -> None: ...

    def click(self, button: Button) -> None: ...

    def sleep(self, seconds: float) -> None: ...


class _NavigationRuntimeHost(Protocol):
    config: _NavigationConfig
    device: _NavigationDevice
    stage_entrance: Mapping[str, object]

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...

    def ui_goto_campaign(self) -> object: ...

    def ui_goto_event(self) -> object: ...

    def ui_goto_sp(self) -> object: ...

    def campaign_ensure_mode(self, mode: str = "normal") -> None: ...

    def campaign_ensure_mode_20241219(self, mode: str = "combat") -> None: ...

    def campaign_ensure_aside_20241219(self, chapter: str) -> None: ...

    def campaign_ensure_chapter(self, chapter: str | int) -> None: ...

    def handle_info_bar(self) -> object: ...

    def is_in_stage(self) -> bool: ...


def _host(runtime: object) -> _NavigationRuntimeHost:
    return cast("_NavigationRuntimeHost", runtime)


def _mapping(value: RuntimeTuningValue, name: str) -> Mapping[str, RuntimeTuningValue]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        message = f"navigation option {name} must be an object"
        raise CampaignRuntimeProfileError(message)
    return cast("Mapping[str, RuntimeTuningValue]", value)


def _sequence(value: RuntimeTuningValue, name: str) -> tuple[RuntimeTuningValue, ...]:
    if not isinstance(value, tuple):
        message = f"navigation option {name} must be a list"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[RuntimeTuningValue, ...]", value)


def _strings(value: RuntimeTuningValue, name: str) -> tuple[str, ...]:
    values = _sequence(value, name)
    if any(not isinstance(item, str) or not item for item in values):
        message = f"navigation option {name} must contain non-empty strings"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[str, ...]", values)


def _string(value: RuntimeTuningValue, name: str) -> str:
    if not isinstance(value, str) or not value:
        message = f"navigation option {name} must be a non-empty string"
        raise CampaignRuntimeProfileError(message)
    return value


def _number(value: RuntimeTuningValue, name: str) -> float:
    if type(value) not in (int, float):
        message = f"navigation option {name} must be a number"
        raise CampaignRuntimeProfileError(message)
    return float(cast("int | float", value))


def _integer_mapping(value: RuntimeTuningValue, name: str) -> Mapping[str, int]:
    values = _mapping(value, name)
    if any(type(item) is not int or item < 0 for item in values.values()):
        message = f"navigation option {name} must map names to non-negative integers"
        raise CampaignRuntimeProfileError(message)
    return cast("Mapping[str, int]", values)


def _string_mapping(value: RuntimeTuningValue, name: str) -> Mapping[str, str]:
    values = _mapping(value, name)
    if any(not isinstance(item, str) or not item for item in values.values()):
        message = f"navigation option {name} must map names to non-empty strings"
        raise CampaignRuntimeProfileError(message)
    return cast("Mapping[str, str]", values)


def _rules(value: RuntimeTuningValue, name: str) -> tuple[Mapping[str, RuntimeTuningValue], ...]:
    values = _sequence(value, name)
    result: list[Mapping[str, RuntimeTuningValue]] = []
    for index, item in enumerate(values):
        result.append(_mapping(item, f"{name}[{index}]"))
    return tuple(result)


def _operations(
    options: Mapping[str, RuntimeTuningValue],
    supported: frozenset[str],
) -> frozenset[str]:
    operations = frozenset(_strings(options["operations"], "operations"))
    unknown = sorted(operations - supported)
    if unknown:
        message = f"unsupported navigation operation: {unknown[0]}"
        raise CampaignRuntimeProfileError(message)
    return operations


def _runtime_result(runtime: object, operation: RuntimeOperation, *args: object, **kwargs: object) -> object:
    return _host(runtime).runtime_super(operation, *args, **kwargs)


def _base_separate_name(name: str) -> tuple[str, str]:
    normalized = name.strip("-")
    if normalized == "sp":
        return "ex_sp", "1"
    if normalized.startswith("extra") or normalized == "ex":
        return "ex_ex", "1"
    if "-" in normalized:
        return cast("tuple[str, str]", tuple(normalized.split("-", maxsplit=1)))
    if normalized.startswith("sp") or normalized[-1:].isdigit():
        return normalized[:-1], normalized[-1]
    return "", ""


class ChapterRoutePlanExecutor(RuntimeExecutorInstance):
    """用有序 typed rules 表达章节别名、入口选择与页面路由。"""

    __slots__ = (
        "_chapter_indices",
        "_entrance_aliases",
        "_entrance_search",
        "_fallback",
        "_mode_policy",
        "_name_rules",
        "_ocr_aliases",
        "_routes",
        "_stage_match_similarity",
    )

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.NAVIGATION)
        operations = _operations(options, _ROUTE_OPERATIONS)
        self._chapter_indices = _integer_mapping(options["chapter_indices"], "chapter_indices")
        self._name_rules = _rules(options["name_rules"], "name_rules")
        self._entrance_aliases = _string_mapping(options["entrance_aliases"], "entrance_aliases")
        self._entrance_search = _mapping(options["entrance_search"], "entrance_search")
        self._ocr_aliases = _string_mapping(options["ocr_aliases"], "ocr_aliases")
        self._routes = _rules(options["routes"], "routes")
        self._validate_routes()
        self._mode_policy = options["mode_policy"]
        self._validate_mode_policy()
        similarity = options["stage_match_similarity"]
        self._stage_match_similarity = None if similarity is None else _number(similarity, "stage_match_similarity")
        self._fallback = _string(options["fallback"], "fallback")
        if self._fallback != "next":
            message = f"unsupported navigation fallback: {self._fallback}"
            raise CampaignRuntimeProfileError(message)

        available = {
            "campaign_ensure_mode": (RuntimeOperation.CAMPAIGN_ENSURE_MODE, self._campaign_ensure_mode),
            "campaign_get_chapter_index": (
                RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX,
                self._campaign_get_chapter_index,
            ),
            "campaign_get_entrance": (RuntimeOperation.CAMPAIGN_GET_ENTRANCE, self._campaign_get_entrance),
            "campaign_match_multi": (RuntimeOperation.CAMPAIGN_MATCH_MULTI, self._campaign_match_multi),
            "campaign_ocr_result_process": (
                RuntimeOperation.CAMPAIGN_OCR_RESULT_PROCESS,
                self._campaign_ocr_result_process,
            ),
            "campaign_separate_name": (
                RuntimeOperation.CAMPAIGN_SEPARATE_NAME,
                self._campaign_separate_name,
            ),
            "campaign_set_chapter": (RuntimeOperation.CAMPAIGN_SET_CHAPTER, self._campaign_set_chapter),
            "campaign_set_chapter_20241219": (
                RuntimeOperation.CAMPAIGN_SET_CHAPTER_20241219,
                self._campaign_set_chapter_20241219,
            ),
            "campaign_set_chapter_event": (
                RuntimeOperation.CAMPAIGN_SET_CHAPTER_EVENT,
                self._campaign_set_chapter_event,
            ),
            "campaign_set_chapter_sp": (
                RuntimeOperation.CAMPAIGN_SET_CHAPTER_SP,
                self._campaign_set_chapter_sp,
            ),
        }
        methods = {operation: method for name, (operation, method) in available.items() if name in operations}
        super().__init__(
            {RuntimeExecutorKind.NAVIGATION},
            methods={RuntimeExecutorKind.NAVIGATION: methods},
        )

    def _validate_mode_policy(self) -> None:
        policy = self._mode_policy
        if isinstance(policy, str):
            if policy not in {"inherited", "noop"}:
                message = f"unsupported navigation mode policy: {policy}"
                raise CampaignRuntimeProfileError(message)
            return
        values = _mapping(policy, "mode_policy")
        kind = values.get("kind")
        if kind not in {"bridge_20241219", "hard_config_override"}:
            message = f"unsupported navigation mode policy kind: {kind!r}"
            raise CampaignRuntimeProfileError(message)
        if "hard_config_override" in values and type(values["hard_config_override"]) is not bool:
            message = "navigation hard_config_override must be a boolean"
            raise CampaignRuntimeProfileError(message)

    def _validate_routes(self) -> None:
        for index, route in enumerate(self._routes):
            destination = _string(route.get("destination"), f"routes[{index}].destination")
            if destination not in {"campaign", "event", "sp"}:
                message = f"unsupported navigation destination: {destination}"
                raise CampaignRuntimeProfileError(message)
            mode = _string(route.get("mode"), f"routes[{index}].mode")
            if mode not in {"requested", "normal", "hard", "ex", "unchanged", "combat"}:
                message = f"unsupported navigation route mode: {mode}"
                raise CampaignRuntimeProfileError(message)
            guard = route.get("guard")
            if guard not in {None, "MAP_CHAPTER_SWITCH_20241219"}:
                message = f"unsupported navigation route guard: {guard!r}"
                raise CampaignRuntimeProfileError(message)

    def _campaign_get_chapter_index(self, runtime: object, name: object) -> object:
        if isinstance(name, int):
            return name
        if not isinstance(name, str):
            return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX, name)
        if name.isdigit():
            return int(name)
        if name in self._chapter_indices:
            return self._chapter_indices[name]
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX, name)

    def _campaign_ocr_result_process(self, runtime: object, result: object) -> object:
        normalized = _runtime_result(runtime, RuntimeOperation.CAMPAIGN_OCR_RESULT_PROCESS, result)
        if not isinstance(normalized, str):
            message = "campaign OCR normalization must return a string"
            raise CampaignRuntimeProfileError(message)
        return self._ocr_aliases.get(normalized, normalized)

    def _campaign_separate_name(self, runtime: object, name: object) -> object:
        if not isinstance(name, str):
            return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SEPARATE_NAME, name)
        for rule in self._name_rules:
            separated = self._match_name_rule(name, rule)
            if separated is not None:
                return separated
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SEPARATE_NAME, name)

    @staticmethod
    def _match_name_rule(
        name: str,
        rule: Mapping[str, RuntimeTuningValue],
    ) -> tuple[str, str] | None:
        names = rule.get("names")
        contains = rule.get("contains")
        prefix = rule.get("prefix")
        if (
            (names is not None and name not in _strings(names, "name_rules.names"))
            or (contains is not None and _string(contains, "name_rules.contains") not in name)
            or (prefix is not None and not name.startswith(_string(prefix, "name_rules.prefix")))
        ):
            return None
        if rule.get("split") == "-":
            if "-" not in name:
                return None
            chapter, stage = name.split("-", maxsplit=1)
            return chapter, stage
        if rule.get("suffix") == "digit" and not name[-1:].isdigit():
            return None

        chapter_value = rule.get("chapter")
        stage_value = rule.get("stage")
        if chapter_value is None or stage_value is None:
            return None
        chapter = name[:-1] if chapter_value == "prefix" else _string(chapter_value, "name_rules.chapter")
        stage = name[-1] if stage_value == "last" else _string(stage_value, "name_rules.stage")
        return chapter, stage

    def _campaign_get_entrance(self, runtime: object, name: object) -> object:
        if not isinstance(name, str):
            return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_GET_ENTRANCE, name)
        selected = self._entrance_aliases.get(name, name)
        if self._entrance_search and name == self._entrance_search.get("input"):
            contains = _string(self._entrance_search["contains"], "entrance_search.contains").lower()
            for stage_name in _host(runtime).stage_entrance:
                if contains in stage_name.lower():
                    selected = stage_name
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_GET_ENTRANCE, selected)

    def _campaign_match_multi(
        self,
        runtime: object,
        template: object,
        image: object,
        stage_image: object = None,
        options: object = None,
        **settings: object,
    ) -> object:
        if self._stage_match_similarity is not None:
            settings["similarity"] = self._stage_match_similarity
        return _runtime_result(
            runtime,
            RuntimeOperation.CAMPAIGN_MATCH_MULTI,
            template,
            image,
            stage_image,
            options,
            **settings,
        )

    def _campaign_ensure_mode(self, runtime: object, mode: object = "normal") -> object:
        if not isinstance(mode, str):
            return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_ENSURE_MODE, mode)
        policy = self._mode_policy
        if policy == "noop":
            return None
        if policy == "inherited":
            return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_ENSURE_MODE, mode)
        values = cast("Mapping[str, RuntimeTuningValue]", policy)
        if mode == "hard" and values.get("hard_config_override", True):
            _host(runtime).config.apply_runtime_overlay(Campaign_Mode="hard")
        if values["kind"] == "bridge_20241219":
            return _host(runtime).campaign_ensure_mode_20241219(mode)
        return None

    def _campaign_set_chapter(self, runtime: object, name: object, mode: object = "normal") -> object:
        if not isinstance(name, str) or not isinstance(mode, str):
            return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SET_CHAPTER, name, mode)
        chapter, stage = self._separate_name_for_route(name)
        if self._apply_first_route(runtime, chapter, stage, mode):
            return None
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SET_CHAPTER, name, mode)

    def _separate_name_for_route(self, name: str) -> tuple[str, str]:
        for rule in self._name_rules:
            separated = self._match_name_rule(name, rule)
            if separated is not None:
                return separated
        return _base_separate_name(name)

    def _campaign_set_chapter_event(self, runtime: object, chapter: object, mode: object = "normal") -> object:
        if isinstance(chapter, str) and isinstance(mode, str) and self._apply_first_route(runtime, chapter, "", mode):
            return True
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SET_CHAPTER_EVENT, chapter, mode)

    def _campaign_set_chapter_sp(self, runtime: object, chapter: object, mode: object = "normal") -> object:
        if isinstance(chapter, str) and isinstance(mode, str) and self._apply_first_route(runtime, chapter, "", mode):
            return True
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SET_CHAPTER_SP, chapter, mode)

    def _campaign_set_chapter_20241219(
        self,
        runtime: object,
        chapter: object,
        stage: object,
        mode: object = "combat",
    ) -> object:
        if (
            isinstance(chapter, str)
            and isinstance(stage, str)
            and isinstance(mode, str)
            and self._apply_first_route(runtime, chapter, stage, mode)
        ):
            return True
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SET_CHAPTER_20241219, chapter, stage, mode)

    def _apply_first_route(self, runtime: object, chapter: str, stage: str, requested_mode: str) -> bool:
        for route in self._routes:
            if self._route_matches(runtime, route, chapter):
                self._apply_route(runtime, route, chapter, stage, requested_mode)
                return True
        return False

    @staticmethod
    def _route_matches(
        runtime: object,
        route: Mapping[str, RuntimeTuningValue],
        chapter: str,
    ) -> bool:
        guard = route.get("guard")
        if guard is not None:
            if guard != "MAP_CHAPTER_SWITCH_20241219":
                message = f"unsupported navigation route guard: {guard!r}"
                raise CampaignRuntimeProfileError(message)
            if not _host(runtime).config.MAP_CHAPTER_SWITCH_20241219:
                return False
        match = route.get("match")
        if match == "*":
            return True
        if match == "numeric":
            return chapter.isdigit()
        chapters = route.get("chapters")
        if chapters is not None and chapter in _strings(chapters, "routes.chapters"):
            return True
        prefix = route.get("prefix")
        return prefix is not None and chapter.startswith(_string(prefix, "routes.prefix"))

    @staticmethod
    def _apply_route(
        runtime: object,
        route: Mapping[str, RuntimeTuningValue],
        chapter: str,
        stage: str,
        requested_mode: str,
    ) -> None:
        host = _host(runtime)
        destination = _string(route["destination"], "routes.destination")
        route_mode = _string(route["mode"], "routes.mode")
        if destination == "campaign":
            ChapterRoutePlanExecutor._apply_campaign_route(
                host,
                route,
                chapter,
                route_mode,
                requested_mode,
            )
            return
        ChapterRoutePlanExecutor._open_route_destination(host, destination)
        if route.get("hard_if") == "campaign_name_is_hard" and chapter.startswith("h"):
            host.config.apply_runtime_overlay(Campaign_Mode="hard")
        ChapterRoutePlanExecutor._apply_route_mode(host, route_mode, requested_mode)
        ChapterRoutePlanExecutor._apply_route_aside(host, route, stage)
        host.campaign_ensure_chapter(chapter)

    @staticmethod
    def _apply_campaign_route(
        host: _NavigationRuntimeHost,
        route: Mapping[str, RuntimeTuningValue],
        chapter: str,
        route_mode: str,
        requested_mode: str,
    ) -> None:
        host.ui_goto_campaign()
        host.campaign_ensure_mode("normal")
        host.campaign_ensure_chapter(chapter)
        selected_mode = requested_mode if route_mode == "requested" else route_mode
        if selected_mode != "hard":
            return
        host.campaign_ensure_mode("hard")
        if route.get("reselect_after_hard") is True:
            host.handle_info_bar()
            host.campaign_ensure_chapter(chapter)

    @staticmethod
    def _open_route_destination(host: _NavigationRuntimeHost, destination: str) -> None:
        if destination == "event":
            host.ui_goto_event()
            return
        if destination == "sp":
            host.ui_goto_sp()
            return
        message = f"unsupported navigation destination: {destination}"
        raise CampaignRuntimeProfileError(message)

    @staticmethod
    def _apply_route_mode(host: _NavigationRuntimeHost, route_mode: str, requested_mode: str) -> None:
        if route_mode in {"normal", "hard", "ex"}:
            host.campaign_ensure_mode(route_mode)
        elif route_mode == "requested":
            host.campaign_ensure_mode(requested_mode)
        elif route_mode == "combat":
            host.campaign_ensure_mode_20241219("combat")
        elif route_mode != "unchanged":
            message = f"unsupported navigation route mode: {route_mode}"
            raise CampaignRuntimeProfileError(message)

    @staticmethod
    def _apply_route_aside(
        host: _NavigationRuntimeHost,
        route: Mapping[str, RuntimeTuningValue],
        stage: str,
    ) -> None:
        aside = route.get("aside")
        aside_by_stage = route.get("aside_by_stage")
        if aside_by_stage is not None:
            for stages, candidate in _string_mapping(aside_by_stage, "routes.aside_by_stage").items():
                if stage in stages.split(","):
                    aside = candidate
                    break
        if aside is not None:
            host.campaign_ensure_aside_20241219(_string(aside, "routes.aside"))


class BallChapterRouteExecutor(RuntimeExecutorInstance):
    """两代活动共用的球色章节路由；Button 资产由封闭表解析。"""

    __slots__ = (
        "_ball",
        "_ball_chapters",
        "_blue_rules",
        "_chapter_indices",
        "_click_wait_seconds",
        "_detected_colors",
        "_event_modes",
        "_hard_chapters",
        "_normal_chapters",
        "_operation_order",
        "_sp_destination",
    )

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.NAVIGATION)
        operations = _operations(options, _BALL_OPERATIONS)
        self._chapter_indices = _integer_mapping(options["chapter_indices"], "chapter_indices")
        if options["main_routes"] is not True:
            message = "ball chapter route requires main_routes=true"
            raise CampaignRuntimeProfileError(message)
        self._event_modes = _string_mapping(options["event_modes"], "event_modes")
        self._sp_destination = _string(options["sp_destination"], "sp_destination")
        if self._sp_destination not in {"event", "sp"}:
            message = f"unsupported ball SP destination: {self._sp_destination}"
            raise CampaignRuntimeProfileError(message)
        ball = _mapping(options["ball"], "ball")
        asset = _string(ball["asset"], "ball.asset")
        try:
            self._ball = _BALL_ASSETS[asset]
        except KeyError:
            message = f"unsupported campaign ball asset: {asset}"
            raise CampaignRuntimeProfileError(message) from None
        self._ball_chapters = frozenset(_strings(ball["chapters"], "ball.chapters"))
        self._normal_chapters = frozenset(_strings(ball["normal_chapters"], "ball.normal_chapters"))
        self._hard_chapters = frozenset(_strings(ball["hard_chapters"], "ball.hard_chapters"))
        self._blue_rules = _rules(ball["blue_rules"], "ball.blue_rules")
        self._operation_order = _strings(ball["operation_order"], "ball.operation_order")
        if set(self._operation_order) != {"set_ball", "ensure_mode"} or len(self._operation_order) != 2:
            message = "ball operation_order must contain set_ball and ensure_mode exactly once"
            raise CampaignRuntimeProfileError(message)
        self._detected_colors = _string_mapping(ball["detected_colors"], "ball.detected_colors")
        self._click_wait_seconds = _number(ball["click_wait_seconds"], "ball.click_wait_seconds")
        if self._click_wait_seconds < 0:
            message = "ball click_wait_seconds must be non-negative"
            raise CampaignRuntimeProfileError(message)

        available = {
            "_campaign_ball_get": (RuntimeOperation.CAMPAIGN_BALL_GET, self._campaign_ball_get),
            "_campaign_ball_set": (RuntimeOperation.CAMPAIGN_BALL_SET, self._campaign_ball_set),
            "_campaign_ball_status": (RuntimeOperation.CAMPAIGN_BALL_STATUS, self._campaign_ball_status),
            "_campaign_ensure_ball_mode": (
                RuntimeOperation.CAMPAIGN_ENSURE_BALL_MODE,
                self._campaign_ensure_ball_mode,
            ),
            "campaign_get_chapter_index": (
                RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX,
                self._campaign_get_chapter_index,
            ),
            "campaign_set_chapter": (RuntimeOperation.CAMPAIGN_SET_CHAPTER, self._campaign_set_chapter),
            "campaign_set_chapter_ball": (
                RuntimeOperation.CAMPAIGN_SET_CHAPTER_BALL,
                self._campaign_set_chapter_ball,
            ),
            "campaign_set_chapter_event": (
                RuntimeOperation.CAMPAIGN_SET_CHAPTER_EVENT,
                self._campaign_set_chapter_event,
            ),
            "campaign_set_chapter_main": (
                RuntimeOperation.CAMPAIGN_SET_CHAPTER_MAIN,
                self._campaign_set_chapter_main,
            ),
            "campaign_set_chapter_sp": (
                RuntimeOperation.CAMPAIGN_SET_CHAPTER_SP,
                self._campaign_set_chapter_sp,
            ),
        }
        methods = {operation: method for name, (operation, method) in available.items() if name in operations}
        super().__init__(
            {RuntimeExecutorKind.NAVIGATION},
            methods={RuntimeExecutorKind.NAVIGATION: methods},
        )

    def _campaign_get_chapter_index(self, runtime: object, name: object) -> object:
        if isinstance(name, int):
            return name
        if isinstance(name, str):
            if name.isdigit():
                return int(name)
            if name in self._chapter_indices:
                return self._chapter_indices[name]
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX, name)

    def _campaign_set_chapter(self, runtime: object, name: object, mode: object = "normal") -> object:
        if not isinstance(name, str) or not isinstance(mode, str):
            return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SET_CHAPTER, name, mode)
        chapter, stage = _base_separate_name(name)
        if (
            self._campaign_set_chapter_main(runtime, chapter, mode)
            or self._campaign_set_chapter_event(runtime, chapter, mode)
            or self._campaign_set_chapter_sp(runtime, chapter, mode)
            or self._campaign_set_chapter_ball(runtime, chapter, stage)
        ):
            return None
        return _runtime_result(runtime, RuntimeOperation.CAMPAIGN_SET_CHAPTER, name, mode)

    @staticmethod
    def _campaign_set_chapter_main(runtime: object, chapter: object, mode: object = "normal") -> bool:
        if not isinstance(chapter, str) or not chapter.isdigit() or not isinstance(mode, str):
            return False
        host = _host(runtime)
        host.ui_goto_campaign()
        host.campaign_ensure_mode("normal")
        host.campaign_ensure_chapter(chapter)
        if mode == "hard":
            host.campaign_ensure_mode("hard")
        return True

    def _campaign_set_chapter_event(self, runtime: object, chapter: object, mode: object = "normal") -> bool:
        del mode
        if not isinstance(chapter, str):
            return False
        campaign_mode = self._event_modes.get(chapter)
        if campaign_mode is None:
            return False
        host = _host(runtime)
        host.ui_goto_event()
        host.campaign_ensure_mode(campaign_mode)
        host.campaign_ensure_chapter(chapter)
        return True

    def _campaign_set_chapter_sp(self, runtime: object, chapter: object, mode: object = "normal") -> bool:
        del mode
        if chapter != "sp":
            return False
        host = _host(runtime)
        if self._sp_destination == "event":
            host.ui_goto_event()
        else:
            host.ui_goto_sp()
        host.campaign_ensure_chapter("sp")
        return True

    def _campaign_set_chapter_ball(self, runtime: object, chapter: object, stage: object) -> bool:
        if not isinstance(chapter, str) or not isinstance(stage, str) or chapter not in self._ball_chapters:
            return False
        host = _host(runtime)
        host.ui_goto_event()
        for operation in self._operation_order:
            if operation == "set_ball":
                self._campaign_ball_set(runtime, self._campaign_ball_status(runtime, chapter, stage))
            else:
                self._campaign_ensure_ball_mode(runtime, chapter)
        host.campaign_ensure_chapter(1)
        return True

    def _campaign_ball_status(self, runtime: object, *args: object) -> str:
        del runtime
        if len(args) == 1 and isinstance(args[0], str):
            chapter = None
            stage = args[0]
        elif len(args) == 2 and all(isinstance(item, str) for item in args):
            chapter, stage = cast("tuple[str, str]", args)
        else:
            message = "campaign ball status requires stage or chapter and stage"
            raise CampaignRuntimeProfileError(message)
        for rule in self._blue_rules:
            chapters = rule.get("chapters")
            if chapters is not None and chapter not in _strings(chapters, "ball.blue_rules.chapters"):
                continue
            if stage in _strings(rule["stages"], "ball.blue_rules.stages"):
                return "blue"
        return "red"

    def _campaign_ensure_ball_mode(self, runtime: object, chapter: object) -> None:
        if not isinstance(chapter, str):
            message = "campaign ball chapter must be a string"
            raise CampaignRuntimeProfileError(message)
        if chapter in self._normal_chapters:
            _host(runtime).campaign_ensure_mode("normal")
            return
        if chapter in self._hard_chapters:
            _host(runtime).campaign_ensure_mode("hard")
            return
        message = f"unsupported campaign ball chapter: {chapter}"
        raise CampaignRuntimeProfileError(message)

    def _campaign_ball_get(self, runtime: object) -> str:
        color = get_color(_host(runtime).device.image, self._ball.area)
        index = max(range(len(color)), key=lambda item: color[item])
        return self._detected_colors.get(str(index), "unknown")

    def _campaign_ball_set(self, runtime: object, status: object) -> None:
        if status not in {"blue", "red"}:
            message = f"unsupported campaign ball status: {status!r}"
            raise CampaignRuntimeProfileError(message)
        host = _host(runtime)
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                host.device.screenshot()
            if self._campaign_ball_get(runtime) == status:
                return
            if host.is_in_stage():
                host.device.click(self._ball)
                host.device.sleep(self._click_wait_seconds)
                while True:
                    host.device.screenshot()
                    if host.is_in_stage():
                        break


def _build_chapter_route_plan(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return ChapterRoutePlanExecutor(context)


def _build_ball_chapter_route(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return BallChapterRouteExecutor(context)


def navigation_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("navigation/chapter_route_plan"),
            {
                RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "operations",
                            "chapter_indices",
                            "name_rules",
                            "entrance_aliases",
                            "entrance_search",
                            "ocr_aliases",
                            "routes",
                            "mode_policy",
                            "stage_match_similarity",
                            "fallback",
                        }
                    )
                )
            },
            _build_chapter_route_plan,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("navigation/ball_chapter_route"),
            {
                RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "operations",
                            "chapter_indices",
                            "main_routes",
                            "event_modes",
                            "sp_destination",
                            "ball",
                        }
                    )
                )
            },
            _build_ball_chapter_route,
        ),
    )
