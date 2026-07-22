from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable


class MapTransitionRuntime(Protocol):
    def handle_in_stage(self) -> bool: ...

    def is_stage_page_has_entrance(self) -> bool: ...

    def is_event_animation(self) -> bool: ...


class MapTransitionCombatRuntime(MapTransitionRuntime, Protocol):
    battle_count: int


@runtime_checkable
class MapTransitionAnimation(Protocol):
    def is_visible(self, runtime: MapTransitionRuntime) -> bool: ...


@runtime_checkable
class WaitableMapTransitionAnimation(MapTransitionAnimation, Protocol):
    def wait_until_closed(self, runtime: MapTransitionRuntime) -> bool: ...


class MapTransitionUi(Protocol):
    """地图、关卡页与活动动画之间的显式 UI 过渡能力。"""

    def handle_stage_return(self, runtime: MapTransitionRuntime) -> bool: ...

    def stage_page_ready(self, runtime: MapTransitionRuntime) -> bool: ...

    def event_animation_visible(self, runtime: MapTransitionRuntime) -> bool: ...

    def combat_end_override(self, runtime: MapTransitionCombatRuntime) -> Callable[[], bool] | None: ...


class _StandardMapTransitionAnimation(MapTransitionAnimation):
    @override
    def is_visible(self, runtime: MapTransitionRuntime) -> bool:
        return runtime.is_event_animation()


STANDARD_MAP_TRANSITION_ANIMATION: MapTransitionAnimation = _StandardMapTransitionAnimation()


class _StandardMapTransitionUi(MapTransitionUi):
    @override
    def handle_stage_return(self, runtime: MapTransitionRuntime) -> bool:
        # 标准组件通过 runtime hook 执行 MaritimeEscort 等当前非声明式流程。
        return runtime.handle_in_stage()

    @override
    def stage_page_ready(self, runtime: MapTransitionRuntime) -> bool:
        return runtime.is_stage_page_has_entrance()

    @override
    def event_animation_visible(self, runtime: MapTransitionRuntime) -> bool:
        return STANDARD_MAP_TRANSITION_ANIMATION.is_visible(runtime)

    @override
    def combat_end_override(self, runtime: MapTransitionCombatRuntime) -> Callable[[], bool] | None:
        del runtime
        return None


STANDARD_MAP_TRANSITION_UI: MapTransitionUi = _StandardMapTransitionUi()
