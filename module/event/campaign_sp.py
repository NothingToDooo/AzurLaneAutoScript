from contextlib import suppress
from pathlib import Path

from module.config.config import TaskEnd
from module.event.base import EventBase
from module.logger import logger


class CampaignSP(EventBase):
    def run(self, name: str = "", folder: str = "campaign_main", mode: str = "normal", total: int = 0) -> None:
        _ = (name, folder, mode, total)
        if not Path(f"./campaign/{self.config.Campaign_Event}/sp.py").exists():
            logger.info(f"./campaign/{self.config.Campaign_Event}/sp.py not exists")
            logger.info("This event do not have SP, skip")
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        with suppress(TaskEnd):
            super().run(name=self.config.Campaign_Name, folder=self.config.Campaign_Event, total=1)
        if self.run_count > 0:
            self.config.task_delay(server_update=True)
        else:
            self.config.task_stop()
