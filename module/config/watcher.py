from datetime import UTC, datetime
from pathlib import Path

from module.config.utils import DEFAULT_TIME, filepath_config
from module.logger import logger


class ConfigWatcher:
    config_name = "alas"
    start_mtime = DEFAULT_TIME

    def start_watching(self) -> None:
        self.start_mtime = self.get_mtime()

    def get_mtime(self) -> datetime:
        timestamp = Path(filepath_config(self.config_name)).stat().st_mtime
        return datetime.fromtimestamp(timestamp, tz=UTC).astimezone().replace(tzinfo=None, microsecond=0)

    def should_reload(self) -> bool:
        mtime = self.get_mtime()
        if mtime > self.start_mtime:
            logger.info(f'Config "{self.config_name}" changed at {mtime}')
            return True
        return False
