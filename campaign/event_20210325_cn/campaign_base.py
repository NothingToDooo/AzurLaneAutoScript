from typing import TYPE_CHECKING

from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.logger import logger

if TYPE_CHECKING:
    from module.map.camera import FullScanOptions
    from module.map.map_grids import SelectedGrids
    from module.map.type_alias import GridMode
    from module.map_detection.grid_info import GridInfo


class CampaignBase(CampaignBase_):
    """该活动 BD 章中的 Siren_Dace 会随舰队移动暂时消失后重现，但自身不移动。

    全图扫描期间暂存并恢复它，避免追踪塞壬移动时丢失。
    """

    dace: SelectedGrids[GridInfo] | None = None

    def full_scan_movable(self, *, enemy_cleared: bool = True) -> None:
        self.dace = self.map.select(enemy_genre="Siren_Dace")
        logger.attr("Submarine_Dace", self.dace)

        super().full_scan_movable(enemy_cleared=enemy_cleared)

    def full_scan(
        self,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        super().full_scan(options, queue, must_scan, mode)

        if self.dace is not None:
            logger.attr("Submarine_Dace", self.dace)
            for grid in self.dace:
                grid.is_siren = True
                grid.enemy_genre = "Siren_Dace"
            self.dace = None

    def get_map_clear_percentage(self) -> float:
        """第 1 章进度条最多约显示 70%，乘以 1.4 校正后返回 0～1。"""
        value = super().get_map_clear_percentage()
        chapter, _ = self.campaign_separate_name(str(self.MAP.name).lower())
        chapter = self.campaign_get_chapter_index(chapter)
        if chapter == 1:
            value *= 1.4
        return value
