from dataclasses import dataclass


@dataclass(slots=True)
class SwipeVectorOptions:
    box: tuple[int, int, int, int] = (123, 159, 1175, 628)
    random_range: tuple[int, int, int, int] = (0, 0, 0, 0)
    padding: int = 15
    duration: object = (0.1, 0.2)
    whitelist_area: object = None
    blacklist_area: object = None
    name: str = "SWIPE"
    distance_check: bool = True
