from typing import TYPE_CHECKING, cast

from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue

from .campaign_runtime_grids import (
    BossIconAsSirenGrid,
    BossIconAsSirenWithCurrentFleetGrid,
    CurrentFleetColorGrid,
    StrongCurrentFleetColorGrid,
    W15BossAsSirenGrid,
    WarmBossIconAsSirenGrid,
    WeakCurrentFleetTemplateGrid,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .campaign_runtime_profile import RuntimeExecutorFactory


def _options(
    context: RuntimeExecutorBuildContext,
    kind: RuntimeExecutorKind,
) -> Mapping[str, RuntimeTuningValue]:
    return context.options(kind)


def _expect(options: Mapping[str, RuntimeTuningValue], name: str, expected: object) -> None:
    actual = options[name]
    if actual != expected:
        message = f"runtime grid option {name} mismatch: expected={expected!r}, actual={actual!r}"
        raise CampaignRuntimeProfileError(message)


def _operations(options: Mapping[str, RuntimeTuningValue], expected: frozenset[str]) -> None:
    value = options["operations"]
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        message = "runtime grid operations must contain strings"
        raise CampaignRuntimeProfileError(message)
    actual = frozenset(cast("tuple[str, ...]", value))
    if actual != expected:
        message = f"runtime grid operations mismatch: expected={sorted(expected)}, actual={sorted(actual)}"
        raise CampaignRuntimeProfileError(message)


def _validate_boss_icon_options(
    options: Mapping[str, RuntimeTuningValue],
    *,
    color: tuple[int, int, int],
    operations: frozenset[str],
) -> None:
    _operations(options, operations)
    _expect(options, "crop", (0, -0.2, 0.8, 0.2))
    _expect(options, "color", color)
    _expect(options, "color_threshold", 221)
    _expect(options, "min_pixels", 30)
    _expect(options, "template", "TEMPLATE_ENEMY_BOSS")
    _expect(options, "similarity", 0.6)
    _expect(options, "scaling", 0.5)
    _expect(options, "genre", "Siren_Siren")


def _build_map_boss_as_siren(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _options(context, RuntimeExecutorKind.MAP_GRID_RECOGNITION)
    _operations(options, frozenset({"merge"}))
    _expect(options, "enemy_genre", "")
    _expect(options, "enemy_scale", 0)
    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.MAP_GRID_RECOGNITION},
        map_grid_class=W15BossAsSirenGrid,
    )


def _build_boss_icon_as_siren(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _options(context, RuntimeExecutorKind.CAMERA_GRID_RECOGNITION)
    _validate_boss_icon_options(
        options,
        color=(255, 150, 24),
        operations=frozenset({"predict_boss", "predict_enemy_genre"}),
    )
    _expect(options, "suppress_boss", expected=True)
    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.CAMERA_GRID_RECOGNITION},
        camera_grid_class=BossIconAsSirenGrid,
    )


def _build_boss_icon_with_current_fleet(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _options(context, RuntimeExecutorKind.CAMERA_GRID_RECOGNITION)
    _validate_boss_icon_options(
        options,
        color=(255, 150, 24),
        operations=frozenset({"predict_boss", "predict_current_fleet", "predict_enemy_genre"}),
    )
    _expect(options, "suppress_boss", expected=True)
    _expect(options, "current_fleet_min_pixels", 200)
    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.CAMERA_GRID_RECOGNITION},
        camera_grid_class=BossIconAsSirenWithCurrentFleetGrid,
    )


def _build_boss_icon_color(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _options(context, RuntimeExecutorKind.CAMERA_GRID_RECOGNITION)
    _validate_boss_icon_options(
        options,
        color=(255, 190, 84),
        operations=frozenset({"predict_enemy_genre"}),
    )
    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.CAMERA_GRID_RECOGNITION},
        camera_grid_class=WarmBossIconAsSirenGrid,
    )


def _build_current_fleet_color(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _options(context, RuntimeExecutorKind.CAMERA_GRID_RECOGNITION)
    _operations(options, frozenset({"predict_current_fleet"}))
    min_pixels = options["min_pixels"]
    if min_pixels == 200:
        grid_class = CurrentFleetColorGrid
    elif min_pixels == 600:
        grid_class = StrongCurrentFleetColorGrid
    else:
        message = f"unsupported current-fleet color threshold: {min_pixels!r}"
        raise CampaignRuntimeProfileError(message)
    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.CAMERA_GRID_RECOGNITION},
        camera_grid_class=grid_class,
    )


def _build_weak_current_fleet_template(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _options(context, RuntimeExecutorKind.CAMERA_GRID_RECOGNITION)
    _operations(options, frozenset({"predict_current_fleet"}))
    _expect(options, "min_pixels", 150)
    _expect(options, "color", (24, 255, 107))
    _expect(options, "template", "TEMPLATE_FLEET_CURRENT")
    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.CAMERA_GRID_RECOGNITION},
        camera_grid_class=WeakCurrentFleetTemplateGrid,
    )


def _descriptor(
    implementation: str,
    kind: RuntimeExecutorKind,
    required: frozenset[str],
    factory: RuntimeExecutorFactory,
) -> RuntimeExecutorFactoryDescriptor:
    return RuntimeExecutorFactoryDescriptor(
        RuntimeImplementationId(implementation),
        {kind: RuntimeExecutorOptionsSchema(required=required)},
        factory,
    )


_BOSS_ICON_OPTIONS = frozenset(
    {
        "operations",
        "crop",
        "color",
        "color_threshold",
        "min_pixels",
        "template",
        "similarity",
        "scaling",
        "genre",
    }
)


def grid_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    camera = RuntimeExecutorKind.CAMERA_GRID_RECOGNITION
    return (
        _descriptor(
            "map_grid/boss_as_siren",
            RuntimeExecutorKind.MAP_GRID_RECOGNITION,
            frozenset({"operations", "enemy_genre", "enemy_scale"}),
            _build_map_boss_as_siren,
        ),
        _descriptor(
            "camera_grid/boss_icon_as_siren",
            camera,
            _BOSS_ICON_OPTIONS | {"suppress_boss"},
            _build_boss_icon_as_siren,
        ),
        _descriptor(
            "camera_grid/boss_icon_as_siren_with_current_fleet",
            camera,
            _BOSS_ICON_OPTIONS | {"suppress_boss", "current_fleet_min_pixels"},
            _build_boss_icon_with_current_fleet,
        ),
        _descriptor(
            "camera_grid/boss_icon_color",
            camera,
            _BOSS_ICON_OPTIONS,
            _build_boss_icon_color,
        ),
        _descriptor(
            "camera_grid/current_fleet_color",
            camera,
            frozenset({"operations", "min_pixels"}),
            _build_current_fleet_color,
        ),
        _descriptor(
            "camera_grid/weak_current_fleet_template",
            camera,
            frozenset({"operations", "min_pixels", "color", "template"}),
            _build_weak_current_fleet_template,
        ),
    )
