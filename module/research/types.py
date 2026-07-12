from typing import NotRequired, TypedDict


class ResearchProjectData(TypedDict):
    name: str
    series: int
    time: int
    need_coin: NotRequired[bool]
    need_cube: NotRequired[bool]
    need_part: NotRequired[bool]
    equipment_amount: NotRequired[int]
    ship: NotRequired[str]
    ship_rarity: NotRequired[str]
