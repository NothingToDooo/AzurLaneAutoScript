from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from module.base.button import Button
from module.campaign.assets import (
    EVENT_20201126_DETAIL,
    EVENT_20201126_DETAIL_CHECK,
    EVENT_20201126_DETAIL_WHITE,
    EVENT_20201126_ENTRANCE,
    EVENT_20201126_PT_ICON,
    EVENT_20250424_PT_ICON,
    EVENT_20250724_PT_ICON,
    EVENT_20260417_DETAIL,
    EVENT_20260417_DETAIL_CHECK,
    EVENT_20260417_DETAIL_WHITE,
    EVENT_20260417_ENTRANCE,
    EVENT_20260417_PT_ICON,
)
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.logger import logger
from module.ui.page import page_campaign_menu, page_event, page_main_white

from .campaign_event_ui import (
    CampaignEventCombatResultContributor,
    CampaignEventUiContributor,
    CampaignEventUiExecutor,
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
    from collections.abc import Iterable

    from module.campaign.event_destination import EventDestinationHost
    from module.combat.combat_result_ui import CombatResultRuntime

    from .campaign_event_ui import EventCombatResultNext


_ANIMATION_PINK = Button(
    area=(1186, 446, 1272, 493),
    color=(255, 153, 172),
    button=(1186, 446, 1272, 493),
    name="ANIMATION_PINK",
)
_ANIMATION_ORANGE = Button(
    area=(1186, 446, 1272, 493),
    color=(255, 177, 123),
    button=(1186, 446, 1272, 493),
    name="ANIMATION_ORANGE",
)
_ANIMATION_BLUE = Button(
    area=(1186, 446, 1272, 493),
    color=(176, 192, 251),
    button=(1186, 446, 1272, 493),
    name="ANIMATION_BLUE",
)
_EVENT_ANIMATION = Button(
    area=(49, 229, 119, 400),
    color=(118, 215, 240),
    button=(49, 229, 119, 400),
    name="EVENT_ANIMATION",
)

_BUTTONS: Mapping[str, Button] = {
    "ANIMATION_PINK": _ANIMATION_PINK,
    "ANIMATION_ORANGE": _ANIMATION_ORANGE,
    "ANIMATION_BLUE": _ANIMATION_BLUE,
    "EVENT_ANIMATION": _EVENT_ANIMATION,
    "EVENT_20201126_DETAIL": EVENT_20201126_DETAIL,
    "EVENT_20201126_DETAIL_CHECK": EVENT_20201126_DETAIL_CHECK,
    "EVENT_20201126_DETAIL_WHITE": EVENT_20201126_DETAIL_WHITE,
    "EVENT_20201126_ENTRANCE": EVENT_20201126_ENTRANCE,
    "EVENT_20201126_PT_ICON": EVENT_20201126_PT_ICON,
    "EVENT_20250424_PT_ICON": EVENT_20250424_PT_ICON,
    "EVENT_20250724_PT_ICON": EVENT_20250724_PT_ICON,
    "EVENT_20260417_DETAIL": EVENT_20260417_DETAIL,
    "EVENT_20260417_DETAIL_CHECK": EVENT_20260417_DETAIL_CHECK,
    "EVENT_20260417_DETAIL_WHITE": EVENT_20260417_DETAIL_WHITE,
    "EVENT_20260417_ENTRANCE": EVENT_20260417_ENTRANCE,
    "EVENT_20260417_PT_ICON": EVENT_20260417_PT_ICON,
}
_PAGES: Mapping[str, object] = {
    "campaign_menu": page_campaign_menu,
    "event": page_event,
    "main_white": page_main_white,
}


class _EventUiRuntimeHost(Protocol):
    def appear(
        self,
        button: object,
        *,
        offset: tuple[int, int] | None = None,
    ) -> bool: ...

    def image_color_count(
        self,
        area: tuple[int, int, int, int],
        *,
        color: tuple[int, int, int],
        count: int,
    ) -> bool: ...

    def ui_page_appear(self, page: object) -> bool: ...

    def ui_ensure(self, page: object) -> object: ...

    def ui_goto_main(self) -> object: ...

    def ui_goto(self, page: object) -> object: ...

    def ui_click(
        self,
        button: object,
        *,
        check_button: object,
        appear_button: object | None = None,
        offset: tuple[int, int] | None = None,
    ) -> object: ...

    def is_event_entrance_available(self) -> bool: ...

    def loop(self) -> Iterable[object]: ...


def _host(runtime: object) -> _EventUiRuntimeHost:
    return cast("_EventUiRuntimeHost", runtime)


def _mapping(value: RuntimeTuningValue, name: str) -> Mapping[str, RuntimeTuningValue]:
    if not isinstance(value, Mapping):
        message = f"event UI option {name} must be an object"
        raise CampaignRuntimeProfileError(message)
    return cast("Mapping[str, RuntimeTuningValue]", value)


def _string(values: Mapping[str, RuntimeTuningValue], name: str) -> str:
    value = values[name]
    if not isinstance(value, str) or not value:
        message = f"event UI option {name} must be a non-empty string"
        raise CampaignRuntimeProfileError(message)
    return value


def _integer(values: Mapping[str, RuntimeTuningValue], name: str) -> int:
    value = values[name]
    if type(value) is not int:
        message = f"event UI option {name} must be an integer"
        raise CampaignRuntimeProfileError(message)
    return value


def _int_tuple(
    values: Mapping[str, RuntimeTuningValue],
    name: str,
    length: int,
) -> tuple[int, ...]:
    value = values[name]
    if not isinstance(value, tuple) or len(value) != length or any(type(item) is not int for item in value):
        message = f"event UI option {name} must contain {length} integers"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[int, ...]", value)


def _button(name: str) -> Button:
    try:
        return _BUTTONS[name]
    except KeyError:
        message = f"unsupported event UI asset: {name}"
        raise CampaignRuntimeProfileError(message) from None


def _page(name: str) -> object:
    try:
        return _PAGES[name]
    except KeyError:
        message = f"unsupported event UI page: {name}"
        raise CampaignRuntimeProfileError(message) from None


def _operations(options: Mapping[str, RuntimeTuningValue]) -> frozenset[str]:
    value = options["operations"]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = "event UI operations must contain strings"
        raise CampaignRuntimeProfileError(message)
    return frozenset(cast("tuple[str, ...]", value))


class _Detector(Protocol):
    def detected(self, runtime: _EventUiRuntimeHost) -> bool: ...


class _AssetDetector:
    __slots__ = ("_button",)

    def __init__(self, button: Button) -> None:
        self._button = button

    def detected(self, runtime: _EventUiRuntimeHost) -> bool:
        return runtime.appear(self._button)


class _ColorCountDetector:
    __slots__ = ("_area", "_color", "_count")

    def __init__(
        self,
        area: tuple[int, int, int, int],
        color: tuple[int, int, int],
        count: int,
    ) -> None:
        self._area = area
        self._color = color
        self._count = count

    def detected(self, runtime: _EventUiRuntimeHost) -> bool:
        return runtime.image_color_count(
            self._area,
            color=self._color,
            count=self._count,
        )


def _detector(raw: RuntimeTuningValue) -> _Detector:
    values = _mapping(raw, "detector")
    if set(values) == {"asset"}:
        return _AssetDetector(_button(_string(values, "asset")))
    if set(values) == {"color_count"}:
        color_count = _mapping(values["color_count"], "color_count")
        area = cast("tuple[int, int, int, int]", _int_tuple(color_count, "area", 4))
        color = cast("tuple[int, int, int]", _int_tuple(color_count, "color", 3))
        return _ColorCountDetector(area, color, _integer(color_count, "count"))
    message = "event UI detector must contain exactly one supported detector kind"
    raise CampaignRuntimeProfileError(message)


def _detectors(value: RuntimeTuningValue) -> tuple[_Detector, ...]:
    if not isinstance(value, tuple) or not value:
        message = "event UI detectors must be a non-empty array"
        raise CampaignRuntimeProfileError(message)
    return tuple(_detector(raw) for raw in value)


def _is_detected(runtime: _EventUiRuntimeHost, detectors: tuple[_Detector, ...]) -> bool:
    for detector in detectors:
        if detector.detected(runtime):
            logger.info("Event animation, waiting")
            return True
    return False


def _build_animation_detector(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.EVENT_UI)
    if _operations(options) != {"is_event_animation"}:
        message = "animation detector must expose only is_event_animation"
        raise CampaignRuntimeProfileError(message)
    detectors = _detectors(options["detectors"])

    def is_event_animation(runtime: object) -> object:
        return _is_detected(_host(runtime), detectors)

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.EVENT_UI},
        methods={
            RuntimeExecutorKind.EVENT_UI: {
                RuntimeOperation.IS_EVENT_ANIMATION: is_event_animation,
            }
        },
    )


@dataclass(frozen=True, slots=True)
class _AlreadyAtEvent:
    asset: Button
    offset: tuple[int, int]
    page: object

    @classmethod
    def from_options(cls, raw: RuntimeTuningValue) -> _AlreadyAtEvent:
        options = _mapping(raw, "already")
        return cls(
            asset=_button(_string(options, "asset")),
            offset=cast("tuple[int, int]", _int_tuple(options, "offset", 2)),
            page=_page(_string(options, "page")),
        )


@dataclass(frozen=True, slots=True)
class _EventDetail:
    check: Button
    dark: Button
    white: Button
    white_page: object

    @classmethod
    def from_options(cls, raw: RuntimeTuningValue) -> _EventDetail:
        options = _mapping(raw, "detail")
        return cls(
            check=_button(_string(options, "check")),
            dark=_button(_string(options, "dark")),
            white=_button(_string(options, "white")),
            white_page=_page(_string(options, "white_page")),
        )


@dataclass(frozen=True, slots=True)
class _EventEntrance:
    asset: Button
    check: Button
    appear: Button
    offset: tuple[int, int]

    @classmethod
    def from_options(cls, raw: RuntimeTuningValue) -> _EventEntrance:
        options = _mapping(raw, "entrance")
        return cls(
            asset=_button(_string(options, "asset")),
            check=_button(_string(options, "check")),
            appear=_button(_string(options, "appear")),
            offset=cast("tuple[int, int]", _int_tuple(options, "offset", 2)),
        )


@dataclass(frozen=True, slots=True)
class _DetailEventEntryExecutor:
    already: _AlreadyAtEvent
    menu_page: object
    detail: _EventDetail
    entrance: _EventEntrance
    detectors: tuple[_Detector, ...]

    def open(self, runtime: EventDestinationHost) -> bool:
        host = _host(runtime)
        if host.appear(self.already.asset, offset=self.already.offset) and host.ui_page_appear(self.already.page):
            logger.info("Already at configured detail event")
            return True
        host.ui_ensure(self.menu_page)
        if not host.is_event_entrance_available():
            return False
        host.ui_goto_main()
        if host.ui_page_appear(self.detail.white_page):
            host.ui_click(self.detail.white, check_button=self.detail.check)
        else:
            host.ui_click(self.detail.dark, check_button=self.detail.check)
        host.ui_click(
            self.entrance.asset,
            check_button=self.entrance.check,
            appear_button=self.entrance.appear,
            offset=self.entrance.offset,
        )
        return True

    def is_event_animation(self, runtime: object) -> object:
        return _is_detected(_host(runtime), self.detectors)

    def event_animation_end(self, runtime: object) -> object:
        host = _host(runtime)
        if not _is_detected(host, self.detectors):
            return False
        for _ in host.loop():
            if _is_detected(host, self.detectors):
                continue
            break
        return True


def _validate_detail_operations(operations: frozenset[str], *, wait_until_end: bool) -> None:
    expected = {"is_event_animation"}
    if wait_until_end:
        expected.add("event_animation_end")
    if operations != expected:
        message = f"detail event entry operations mismatch: expected={sorted(expected)}, actual={sorted(operations)}"
        raise CampaignRuntimeProfileError(message)


def _build_detail_event_entry(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.EVENT_UI)
    wait_until_end = options["wait_until_animation_end"]
    if type(wait_until_end) is not bool:
        message = "detail event entry wait option must be a boolean"
        raise CampaignRuntimeProfileError(message)
    _validate_detail_operations(_operations(options), wait_until_end=wait_until_end)
    executor = _DetailEventEntryExecutor(
        already=_AlreadyAtEvent.from_options(options["already"]),
        menu_page=_page(_string(options, "menu_page")),
        detail=_EventDetail.from_options(options["detail"]),
        entrance=_EventEntrance.from_options(options["entrance"]),
        detectors=_detectors(options["animation_detectors"]),
    )
    methods = {RuntimeOperation.IS_EVENT_ANIMATION: executor.is_event_animation}
    if wait_until_end:
        methods[RuntimeOperation.EVENT_ANIMATION_END] = executor.event_animation_end

    return CampaignEventUiExecutor(
        {RuntimeExecutorKind.EVENT_UI},
        CampaignEventUiContributor(destination=executor),
        methods={RuntimeExecutorKind.EVENT_UI: methods},
    )


@dataclass(frozen=True, slots=True)
class _PageEventDestination:
    already: _AlreadyAtEvent
    menu_page: object
    destination: object

    def open(self, runtime: EventDestinationHost) -> bool:
        host = _host(runtime)
        if host.appear(self.already.asset, offset=self.already.offset) and host.ui_page_appear(self.already.page):
            logger.info("Already at configured page event")
            return True
        host.ui_ensure(self.menu_page)
        if not host.is_event_entrance_available():
            return False
        host.ui_goto(self.destination)
        return True


def _build_page_event_entry(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.EVENT_UI)
    destination = _PageEventDestination(
        already=_AlreadyAtEvent.from_options(options["already"]),
        menu_page=_page(_string(options, "menu_page")),
        destination=_page(_string(options, "destination")),
    )
    blocked_page_value = options.get("exp_info_blocked_page")
    blocked_page = None if blocked_page_value is None else _page(cast("str", blocked_page_value))
    combat_result = None
    if blocked_page is not None:

        def handle_experience_result(
            runtime: CombatResultRuntime,
            next_handler: EventCombatResultNext,
        ) -> bool:
            host = _host(runtime)
            if host.ui_page_appear(blocked_page):
                return False
            return next_handler(runtime)

        combat_result = CampaignEventCombatResultContributor(
            handle_experience_result=handle_experience_result,
        )

    return CampaignEventUiExecutor(
        {RuntimeExecutorKind.EVENT_UI},
        CampaignEventUiContributor(
            destination=destination,
            combat_result=combat_result,
        ),
    )


def event_ui_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    event_ui = RuntimeExecutorKind.EVENT_UI
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/animation_detector"),
            {
                event_ui: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "detectors"}),
                )
            },
            _build_animation_detector,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/detail_event_entry"),
            {
                event_ui: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "operations",
                            "already",
                            "menu_page",
                            "detail",
                            "entrance",
                            "animation_detectors",
                            "wait_until_animation_end",
                        }
                    ),
                )
            },
            _build_detail_event_entry,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/page_event_entry"),
            {
                event_ui: RuntimeExecutorOptionsSchema(
                    required=frozenset({"already", "menu_page", "destination"}),
                    optional=frozenset({"exp_info_blocked_page"}),
                )
            },
            _build_page_event_entry,
        ),
    )
