from typing import TYPE_CHECKING

from module.content.campaign_session import CampaignRunVariant

if TYPE_CHECKING:
    from module.content.cell import CellId
    from module.map.map_base import CampaignMap
    from module.map_detection.grid_info import GridInfo


def apply_normal_enemy_candidate_mask(
    map_: CampaignMap,
    candidates: tuple[CellId, ...] | None,
    variant: CampaignRunVariant,
) -> None:
    """在 normal map_data 初始化后投影完整的敌人刷新候选集合。"""

    if variant is CampaignRunVariant.LOOP:
        return
    if variant is not CampaignRunVariant.NORMAL:
        message = "normal enemy candidate mask requires a CampaignRunVariant"
        raise TypeError(message)
    if candidates is None:
        return

    candidate_locations = frozenset((cell.x, cell.y) for cell in candidates)
    assignments: list[tuple[GridInfo, bool]] = []
    map_locations: set[tuple[int, int]] = set()
    for grid in tuple(map_):
        location = grid.location
        if location is None:
            message = "campaign map grid is missing its location"
            raise RuntimeError(message)
        map_locations.add(location)
        assignments.append((grid, location in candidate_locations))
    if missing := candidate_locations - map_locations:
        message = f"normal enemy candidate mask references cells outside the active map: {sorted(missing)}"
        raise ValueError(message)
    for grid, may_enemy in assignments:
        grid.may_enemy = may_enemy
