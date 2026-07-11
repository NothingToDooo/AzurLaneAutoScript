from typing import Never

from module.base.base import ModuleBase
from module.logger import logger


class CampaignSos(ModuleBase):
    def run(self) -> Never:
        """游戏已移除 SOS 地图；禁用并停止该任务。"""
        logger.warning("AL no longer has SOS maps, disable task")
        self.config.Scheduler_Enable = False
        self.config.task_stop()
