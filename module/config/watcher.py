from pathlib import Path
from typing import TYPE_CHECKING

from module.base.time import beijing_from_timestamp
from module.config.utils import DEFAULT_TIME, filepath_config
from module.logger import logger

if TYPE_CHECKING:
    from datetime import datetime


class ConfigWatcher:
    config_name = "alas"
    start_mtime = DEFAULT_TIME

    def start_watching(self) -> None:
        self.start_mtime = self.get_mtime()

    def get_mtime(self) -> datetime:
        """
        Last modify time of the file
        """
        timestamp = Path(filepath_config(self.config_name)).stat().st_mtime
        return beijing_from_timestamp(timestamp).replace(microsecond=0)

    def should_reload(self) -> bool:
        """
        Returns:
            bool: Whether the file has been modified and configs should reload
        """
        mtime = self.get_mtime()
        if mtime > self.start_mtime:
            logger.info(f'Config "{self.config_name}" changed at {mtime}')
            return True
        return False
