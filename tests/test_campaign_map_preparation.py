from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    MapClearPercentageHandler,
    MapClearPercentageNext,
    MapGetInfoHandler,
    MapGetInfoNext,
    build_campaign_map_observer,
)
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
)
from module.content.manifest import load_default_event_manifests
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.handler.fast_forward import AUTO_SEARCH, FastForwardHandler

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.map.map_observer import CampaignMapObserver, MapPreparationRuntime

_IMPLEMENTATION = RuntimeImplementationId("observation/auto_search_clear_status")


@dataclass(slots=True)
class _Config:
    Campaign_Name: str
    MAP_HAS_MAP_STORY: bool = True
    MAP_CLEAR_ALL_THIS_TIME: bool = False
    MAP_CLEAR_PERCENTAGE_SHORT: bool = False
    STAR_REQUIRE_3: int = 0
    StopCondition_MapAchievement: str = ""


class _PreparationRuntime(FastForwardHandler):
    config: _Config

    def __init__(
        self,
        observer: CampaignMapObserver,
        *,
        campaign_name: str = "normal",
        standard_percentage: float = 0.25,
    ) -> None:
        self._map_observer = observer
        self.config = _Config(campaign_name)
        self.standard_percentage = standard_percentage
        self.standard_percentage_calls = 0
        self.auto_search_visible = False
        self.trace: list[str] = []
        self.shown_flags: list[tuple[bool, bool, bool, bool]] = []

    @override
    def _standard_get_map_clear_percentage(self) -> float:
        self.standard_percentage_calls += 1
        self.trace.append("standard_percentage")
        return self.standard_percentage

    @override
    def _is_map_star_active(self, button: Button) -> bool:
        del button
        return False

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del button, offset, interval, similarity, threshold
        return False

    @override
    def map_show_info(self) -> None:
        self.trace.append("show")
        self.shown_flags.append(
            (
                self.map_is_100_percent_clear,
                self.map_is_3_stars,
                self.map_is_threat_safe,
                self.map_has_clear_mode,
            )
        )


def _auto_profile(
    *,
    prefixes: tuple[str, ...] = ("th",),
    override_percentage: bool = True,
    extra_options: dict[str, object] | None = None,
) -> CampaignRuntimeProfile:
    options: dict[str, object] = {
        "campaign_name_prefixes": prefixes,
        "override_map_clear_percentage": override_percentage,
    }
    if extra_options is not None:
        options.update(extra_options)
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("map-preparation-test"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.MAP_OBSERVATION,
                _IMPLEMENTATION,
                options,
            ),
        ),
    )
    return CampaignRuntimeProfile(
        CampaignRuntimeProfileId("map-preparation-test"),
        (extension,),
    )


def _observer_for(
    profile: CampaignRuntimeProfile,
    *,
    multiplier: float = 1.0,
) -> CampaignMapObserver:
    manager = CampaignRuntimeProfileManager(
        profile,
        load_default_campaign_runtime_executor_registry(),
    )
    return build_campaign_map_observer(
        manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION),
        map_clear_percentage_multiplier=multiplier,
    )


def _patch_auto_search(monkeypatch: pytest.MonkeyPatch) -> None:
    def appear(main: object) -> bool:
        return cast("_PreparationRuntime", main).auto_search_visible

    monkeypatch.setattr(AUTO_SEARCH, "appear", appear)


def test_standard_map_info_uses_public_percentage_and_multiplier_once() -> None:
    def percentage(
        runtime: MapPreparationRuntime,
        next_handler: MapClearPercentageNext,
    ) -> float:
        return next_handler(runtime) + 0.1

    observer = build_campaign_map_observer(
        (CampaignMapObserverExecutor(CampaignMapObserverContributor(map_clear_percentage=percentage)),),
        map_clear_percentage_multiplier=2.0,
    )
    runtime = _PreparationRuntime(observer)

    assert runtime.get_map_clear_percentage() == pytest.approx(0.7)
    runtime.map_get_info()

    assert runtime.map_clear_percentage == pytest.approx(0.7)
    assert runtime.standard_percentage_calls == 2


def test_preparation_contributors_compose_later_first() -> None:
    trace: list[str] = []

    def info(label: str) -> MapGetInfoHandler:
        def execute(runtime: MapPreparationRuntime, next_handler: MapGetInfoNext) -> None:
            trace.append(f"{label}:before")
            next_handler(runtime)
            trace.append(f"{label}:after")

        return execute

    def percentage(label: str) -> MapClearPercentageHandler:
        def execute(
            runtime: MapPreparationRuntime,
            next_handler: MapClearPercentageNext,
        ) -> float:
            trace.append(f"{label}:before")
            result = next_handler(runtime)
            trace.append(f"{label}:after")
            return result

        return execute

    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(
                CampaignMapObserverContributor(
                    map_get_info=info("first-info"),
                    map_clear_percentage=percentage("first-percentage"),
                )
            ),
            CampaignMapObserverExecutor(
                CampaignMapObserverContributor(
                    map_get_info=info("second-info"),
                    map_clear_percentage=percentage("second-percentage"),
                )
            ),
        )
    )
    runtime = _PreparationRuntime(observer)

    runtime.map_get_info()

    assert trace == [
        "second-info:before",
        "first-info:before",
        "second-percentage:before",
        "first-percentage:before",
        "first-percentage:after",
        "second-percentage:after",
        "first-info:after",
        "second-info:after",
    ]


def test_auto_search_percentage_overrides_when_visible_and_falls_back_when_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auto_search(monkeypatch)
    runtime = _PreparationRuntime(_observer_for(_auto_profile()))

    runtime.auto_search_visible = True
    assert runtime.get_map_clear_percentage() == pytest.approx(1.0)
    assert runtime.standard_percentage_calls == 0

    runtime.auto_search_visible = False
    assert runtime.get_map_clear_percentage() == pytest.approx(0.25)
    assert runtime.standard_percentage_calls == 1


def test_auto_search_map_info_runs_standard_then_prefix_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auto_search(monkeypatch)
    observer = _observer_for(_auto_profile(override_percentage=False))
    matching = _PreparationRuntime(observer, campaign_name="th3")
    missing = _PreparationRuntime(observer, campaign_name="normal")
    matching.auto_search_visible = True
    missing.auto_search_visible = True

    matching.map_get_info()
    missing.map_get_info()

    assert matching.shown_flags == [
        (False, False, False, False),
        (True, True, True, True),
    ]
    assert missing.shown_flags == [(False, False, False, False)]


@pytest.mark.parametrize(
    ("prefixes", "campaign_name"),
    [
        (("th",), "th3"),
        (("*",), "sp"),
    ],
)
def test_matching_and_wildcard_map_info_still_apply_hidden_auto_search_state(
    monkeypatch: pytest.MonkeyPatch,
    prefixes: tuple[str, ...],
    campaign_name: str,
) -> None:
    _patch_auto_search(monkeypatch)
    runtime = _PreparationRuntime(
        _observer_for(_auto_profile(prefixes=prefixes, override_percentage=False)),
        campaign_name=campaign_name,
    )

    runtime.map_get_info()

    assert runtime.shown_flags == [
        (False, False, False, False),
        (False, False, False, False),
    ]


def test_percentage_override_is_independent_from_prefix_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_auto_search(monkeypatch)
    runtime = _PreparationRuntime(_observer_for(_auto_profile()), campaign_name="normal")
    runtime.auto_search_visible = True

    assert runtime.get_map_clear_percentage() == pytest.approx(1.0)
    runtime.map_get_info()

    assert runtime.shown_flags == [(True, False, False, False)]


def test_preparation_rejects_non_numeric_percentage() -> None:
    def invalid(
        runtime: MapPreparationRuntime,
        next_handler: MapClearPercentageNext,
    ) -> float:
        del runtime, next_handler
        return cast("float", "invalid")

    observer = build_campaign_map_observer(
        (CampaignMapObserverExecutor(CampaignMapObserverContributor(map_clear_percentage=invalid)),)
    )

    with pytest.raises(
        CampaignRuntimeProfileError,
        match="map clear percentage executor must return a number",
    ):
        observer.preparation.get_map_clear_percentage(_PreparationRuntime(observer))


@pytest.mark.parametrize(
    ("pack_id", "stage_id", "profile_id", "overrides_percentage"),
    [
        ("event_20221124_cn", "sp", "profile_784aa473533514b6", False),
        ("event_20221124_cn", "th1", "profile_6e5fee0dfef597c4", False),
        ("event_20221124_cn", "ts1", "profile_d2e67c3f5be2ce51", False),
        ("event_20250724_cn", "ts1", "profile_bb12b0b7d96167de", True),
        ("event_20250724_cn", "ts5", "profile_d70f505533aeb6d8", True),
    ],
)
def test_real_profiles_use_typed_preparation_contributors(
    pack_id: str,
    stage_id: str,
    profile_id: str,
    *,
    overrides_percentage: bool,
) -> None:
    pack = next(pack for pack in load_default_event_manifests() if str(pack.pack_id) == pack_id)
    stage = next(stage for stage in pack.stages if stage.ref.stage_id == stage_id)
    profile = load_default_campaign_runtime_profile_registry().resolve(stage.runtime_profile_id)
    manager = CampaignRuntimeProfileManager(
        profile,
        load_default_campaign_runtime_executor_registry(),
    )
    contributors = [
        instance.map_observer_contributor
        for instance in manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION)
        if isinstance(instance, CampaignMapObserverExecutor)
        and instance.map_observer_contributor.map_get_info is not None
    ]

    assert profile.profile_id.value == profile_id
    assert len(contributors) == 1
    assert (contributors[0].map_clear_percentage is not None) is overrides_percentage
    assert all(
        "operations" not in binding.options
        for extension in profile.extensions
        for binding in extension.executors
        if binding.implementation_id == _IMPLEMENTATION
    )


def test_old_auto_search_operation_schema_is_rejected() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="unknown option: operations"):
        _observer_for(
            _auto_profile(
                extra_options={"operations": ["map_get_info"]},
            )
        )
