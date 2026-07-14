from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

import pytest

from module.adapters import campaign_runtime_navigation as navigation
from module.adapters.campaign_runtime_navigation import navigation_runtime_executor_descriptors
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
)
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
    RuntimeTuningValue,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry

_ROUTE_PLAN = "navigation/chapter_route_plan"
_BALL_ROUTE = "navigation/ball_chapter_route"


class _Device:
    def __init__(self, runtime: _Runtime) -> None:
        self.image = runtime
        self.clicks: list[object] = []
        self.screenshot_count = 0
        self.sleep_seconds: list[float] = []

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def sleep(self, seconds: float) -> None:
        self.sleep_seconds.append(seconds)


class _Runtime:
    def __init__(self, manager: CampaignRuntimeProfileManager) -> None:
        self.manager = manager
        self.calls: list[tuple[object, ...]] = []
        self.device = _Device(self)

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self.manager.invoke_super(operation, self, *args, **kwargs)

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        if "-" in name:
            chapter, stage = name.split("-", maxsplit=1)
            return chapter, stage
        if name[-1].isdigit():
            return name[:-1], name[-1]
        return name, ""

    def ui_goto_campaign(self) -> bool:
        self.calls.append(("destination", "campaign"))
        return True

    def ui_goto_event(self) -> bool:
        self.calls.append(("destination", "event"))
        return True

    def ui_goto_sp(self) -> bool:
        self.calls.append(("destination", "sp"))
        return True

    def campaign_ensure_mode(self, mode: str) -> bool:
        self.calls.append(("mode", mode))
        return True

    def campaign_ensure_mode_20241219(self, mode: str) -> bool:
        self.calls.append(("mode_20241219", mode))
        return True

    def campaign_ensure_aside_20241219(self, aside: str) -> bool:
        self.calls.append(("aside_20241219", aside))
        return True

    def campaign_ensure_chapter(self, chapter: str | int) -> bool:
        self.calls.append(("chapter", chapter))
        return True

    @staticmethod
    def handle_info_bar() -> bool:
        return False

    def is_in_stage(self) -> bool:
        self.calls.append(("is_in_stage",))
        return True


def _unexpected_fallback(*args: object, **kwargs: object) -> object:
    message = f"unexpected navigation fallback: args={args!r}, kwargs={kwargs!r}"
    raise AssertionError(message)


def _content_binding(extension_id: str, implementation: str) -> RuntimeExecutorBinding:
    catalog = load_default_campaign_runtime_profile_registry()
    extension = catalog.extensions[CampaignRuntimeExtensionId(extension_id)]
    matches = tuple(
        binding
        for binding in extension.executors
        if binding.kind is RuntimeExecutorKind.NAVIGATION
        and binding.implementation_id == RuntimeImplementationId(implementation)
    )
    assert len(matches) == 1
    return matches[0]


def _manager(binding: RuntimeExecutorBinding) -> CampaignRuntimeProfileManager:
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("navigation-test"),
        (
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId("navigation-test"),
                (binding,),
            ),
        ),
    )
    return CampaignRuntimeProfileManager(
        profile,
        CampaignRuntimeExecutorRegistry(navigation_runtime_executor_descriptors()),
    )


def _manager_for(extension_id: str, implementation: str = _ROUTE_PLAN) -> CampaignRuntimeProfileManager:
    return _manager(_content_binding(extension_id, implementation))


def _thaw(value: RuntimeTuningValue) -> object:
    if isinstance(value, Mapping):
        values = cast("Mapping[str, RuntimeTuningValue]", value)
        return {key: _thaw(item) for key, item in values.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _mutated_binding(
    extension_id: str,
    implementation: str,
    mutate: Callable[[dict[str, object]], None],
) -> RuntimeExecutorBinding:
    original = _content_binding(extension_id, implementation)
    options = cast("dict[str, object]", _thaw(original.options))
    mutate(options)
    return RuntimeExecutorBinding(
        RuntimeExecutorKind.NAVIGATION,
        RuntimeImplementationId(implementation),
        options,
    )


def test_route_plan_validates_nested_options_during_manager_construction() -> None:
    def invalidate(options: dict[str, object]) -> None:
        routes = cast("list[dict[str, object]]", options["routes"])
        routes[0]["destination"] = "moon"

    with pytest.raises(CampaignRuntimeProfileError):
        _manager(
            _mutated_binding(
                "event_20201029_cn/campaign_base/campaign_base",
                _ROUTE_PLAN,
                invalidate,
            )
        )


def test_ball_route_rejects_assets_outside_the_closed_mapping() -> None:
    def invalidate(options: dict[str, object]) -> None:
        ball = cast("dict[str, object]", options["ball"])
        ball["asset"] = "BALL"

    with pytest.raises(CampaignRuntimeProfileError):
        _manager(
            _mutated_binding(
                "event_20200917_cn/campaign_base/campaign_base",
                _BALL_ROUTE,
                invalidate,
            )
        )


def test_20201029_chapter_index_and_routes_preserve_legacy_semantics() -> None:
    manager = _manager_for("event_20201029_cn/campaign_base/campaign_base")
    runtime = _Runtime(manager)

    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX,
            runtime,
            _unexpected_fallback,
            "ex_sp",
        )
        == 2
    )
    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX,
            runtime,
            _unexpected_fallback,
            "7",
        )
        == 7
    )

    result = manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_SET_CHAPTER,
        runtime,
        _unexpected_fallback,
        "12-4",
        "hard",
    )

    assert result is None
    assert runtime.calls == [
        ("destination", "campaign"),
        ("mode", "normal"),
        ("chapter", "12"),
        ("mode", "hard"),
        ("chapter", "12"),
    ]

    runtime.calls.clear()
    manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_SET_CHAPTER,
        runtime,
        _unexpected_fallback,
        "c3",
        "normal",
    )
    assert runtime.calls == [
        ("destination", "event"),
        ("mode", "hard"),
        ("chapter", "c"),
    ]


def test_20210722_name_rules_are_ordered_and_delegate_unknown_names() -> None:
    manager = _manager_for("event_20210722_cn/campaign_base/campaign_base")
    runtime = _Runtime(manager)

    def separate(name: str) -> tuple[str, str]:
        assert name == "unknown"
        return "base", "9"

    expected = {
        "sp": ("ex_sp", "1"),
        "vsp": ("ex_sp", "1"),
        "extra-stage": ("ex_ex", "1"),
        "d-3": ("d", "3"),
        "sp4": ("sp", "4"),
        "t6": ("t", "6"),
        "unknown": ("base", "9"),
    }
    for name, separated in expected.items():
        fallback = separate if name == "unknown" else _unexpected_fallback
        assert (
            manager.navigation.invoke(
                RuntimeOperation.CAMPAIGN_SEPARATE_NAME,
                runtime,
                fallback,
                name,
            )
            == separated
        )


def test_20210722_chapter_index_and_entrance_alias_are_data_driven() -> None:
    manager = _manager_for("event_20210722_cn/campaign_base/campaign_base")
    runtime = _Runtime(manager)
    delegated: list[str] = []

    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX,
            runtime,
            _unexpected_fallback,
            "ds",
        )
        == 2
    )
    entrance = manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_GET_ENTRANCE,
        runtime,
        lambda name: delegated.append(cast("str", name)) or f"entrance:{name}",
        "sp",
    )

    assert entrance == "entrance:vsp"
    assert delegated == ["vsp"]


def test_20210722_stage_match_uses_the_profile_similarity() -> None:
    manager = _manager_for("event_20210722_cn/campaign_base/campaign_base")
    runtime = _Runtime(manager)
    template = object()
    image = object()
    delegated: list[tuple[object, object, object, object, dict[str, object]]] = []

    def match(
        selected_template: object,
        selected_image: object,
        stage_image: object = None,
        options: object = None,
        **settings: object,
    ) -> list[str]:
        delegated.append((selected_template, selected_image, stage_image, options, settings))
        return ["matched"]

    result = manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_MATCH_MULTI,
        runtime,
        match,
        template,
        image,
    )

    assert result == ["matched"]
    assert delegated == [(template, image, None, None, {"similarity": 0.8})]


def test_ocr_aliases_apply_after_base_normalization() -> None:
    manager = _manager_for("event_20240425_cn/campaign_base/campaign_base")
    runtime = _Runtime(manager)
    delegated: list[str] = []

    def normalize(result: str) -> str:
        delegated.append(result)
        return result.lower()

    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_OCR_RESULT_PROCESS,
            runtime,
            normalize,
            "IISP",
        )
        == "sp"
    )
    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_OCR_RESULT_PROCESS,
            runtime,
            normalize,
            "T1",
        )
        == "t1"
    )
    assert delegated == ["IISP", "T1"]


@pytest.mark.parametrize(
    ("extension_id", "destination"),
    [
        ("event_20220818_cn/campaign_base/campaign_base", "event"),
        ("war_archives_20220818_cn/campaign_base/campaign_base", "sp"),
    ],
)
def test_20220818_shared_rules_preserve_route_destination(
    extension_id: str,
    destination: str,
) -> None:
    manager = _manager_for(extension_id)
    runtime = _Runtime(manager)
    delegated: list[str] = []

    assert manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_SEPARATE_NAME,
        runtime,
        _unexpected_fallback,
        "esp",
    ) == ("sp_sp", "2")
    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX,
            runtime,
            _unexpected_fallback,
            "sp_ex",
        )
        == 3
    )
    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_GET_ENTRANCE,
            runtime,
            lambda name: delegated.append(cast("str", name)) or name,
            "sp",
        )
        == "esp"
    )

    result = manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_SET_CHAPTER_SP,
        runtime,
        _unexpected_fallback,
        "sp_sp",
        "normal",
    )

    assert result is True
    assert delegated == ["esp"]
    assert runtime.calls == [
        ("destination", destination),
        ("chapter", "sp_sp"),
    ]


@pytest.mark.parametrize(("stage", "aside"), [("2", "part1"), ("5", "part2")])
def test_20241024_route_selects_combat_mode_and_stage_aside(stage: str, aside: str) -> None:
    manager = _manager_for("event_20241024_cn/campaign_base/campaign_base")
    runtime = _Runtime(manager)

    result = manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_SET_CHAPTER_20241219,
        runtime,
        _unexpected_fallback,
        "t",
        stage,
        "story",
    )

    assert result is True
    assert runtime.calls == [
        ("destination", "event"),
        ("mode_20241219", "combat"),
        ("aside_20241219", aside),
        ("chapter", "t"),
    ]


@pytest.mark.parametrize(
    ("extension_id", "arguments", "expected"),
    [
        ("event_20200917_cn/campaign_base/campaign_base", ("1",), "blue"),
        ("event_20200917_cn/campaign_base/campaign_base", ("5",), "red"),
        ("event_20230525_cn/campaign_base/campaign_base", ("t", "3"), "blue"),
        ("event_20230525_cn/campaign_base/campaign_base", ("ts", "2"), "red"),
    ],
)
def test_ball_blue_rules_preserve_both_legacy_signatures(
    extension_id: str,
    arguments: tuple[str, ...],
    expected: str,
) -> None:
    manager = _manager_for(extension_id, _BALL_ROUTE)
    runtime = _Runtime(manager)

    assert (
        manager.navigation.invoke(
            RuntimeOperation.CAMPAIGN_BALL_STATUS,
            runtime,
            _unexpected_fallback,
            *arguments,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("extension_id", "expected_area", "expected_calls"),
    [
        (
            "event_20200917_cn/campaign_base/campaign_base",
            (571, 283, 696, 387),
            [
                ("destination", "event"),
                ("ball", (571, 283, 696, 387)),
                ("mode", "normal"),
                ("chapter", 1),
            ],
        ),
        (
            "event_20230525_cn/campaign_base/campaign_base",
            (589, 279, 685, 374),
            [
                ("destination", "event"),
                ("mode", "normal"),
                ("ball", (589, 279, 685, 374)),
                ("chapter", 1),
            ],
        ),
    ],
)
def test_ball_operation_order_and_closed_asset_mapping(
    monkeypatch: pytest.MonkeyPatch,
    extension_id: str,
    expected_area: tuple[int, int, int, int],
    expected_calls: list[tuple[object, ...]],
) -> None:
    manager = _manager_for(extension_id, _BALL_ROUTE)
    runtime = _Runtime(manager)

    def get_color(image: object, area: tuple[int, int, int, int]) -> tuple[int, int, int]:
        host = cast("_Runtime", image)
        host.calls.append(("ball", area))
        return 10, 20, 100

    monkeypatch.setattr(navigation, "get_color", get_color)

    result = manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_SET_CHAPTER,
        runtime,
        _unexpected_fallback,
        "t1",
        "normal",
    )

    assert result is None
    assert expected_area in {call[1] for call in runtime.calls if call[0] == "ball"}
    assert runtime.calls == expected_calls
    assert runtime.device.clicks == []
    assert runtime.device.screenshot_count == 0
    assert runtime.device.sleep_seconds == []
