from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from module.base.type_alias import Area

type Duration = int | float | str | tuple[int | float, int | float]


@dataclass(slots=True)
class SwipeVectorOptions:
    box: Area = (123, 159, 1175, 628)
    random_range: tuple[int, int, int, int] = (0, 0, 0, 0)
    padding: int = 15
    duration: Duration = (0.1, 0.2)
    whitelist_area: list[Area] | None = None
    blacklist_area: list[Area] | None = None
    name: str = "SWIPE"
    distance_check: bool = True
