from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from module.base.type_alias import Area, Point

type MapSwipeBox = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class MapSwipeRequest:
    vector: Point
    explicit_box: Area | None = None


@dataclass(frozen=True, slots=True)
class MapSwipePolicy:
    default_box: MapSwipeBox

    def __post_init__(self) -> None:
        if type(self.default_box) is not tuple or any(type(value) is not int for value in self.default_box):
            message = "map swipe policy default_box must be a canonical integer tuple"
            raise TypeError(message)
        if len(self.default_box) != 4:
            message = "map swipe policy default_box must contain four coordinates"
            raise ValueError(message)


STANDARD_MAP_SWIPE_POLICY = MapSwipePolicy(default_box=(123, 159, 1175, 628))


class MapSwipeRuntime(Protocol):
    def _standard_map_swipe(self, vector: Point, *, box: Area) -> bool: ...


@dataclass(frozen=True, slots=True)
class MapSwipeService:
    policy: MapSwipePolicy = STANDARD_MAP_SWIPE_POLICY

    def __post_init__(self) -> None:
        if not isinstance(self.policy, MapSwipePolicy):
            message = "map swipe service requires a MapSwipePolicy"
            raise TypeError(message)

    def swipe(
        self,
        runtime: MapSwipeRuntime,
        request: MapSwipeRequest,
    ) -> bool:
        if not isinstance(request, MapSwipeRequest):
            message = "map swipe service requires a MapSwipeRequest"
            raise TypeError(message)
        box = request.explicit_box if request.explicit_box is not None else self.policy.default_box
        return runtime._standard_map_swipe(  # ruff:ignore[private-member-access] - typed service 负责调用算法 primitive。
            request.vector,
            box=box,
        )


STANDARD_MAP_SWIPE_SERVICE = MapSwipeService()
