import os
import shutil
from contextlib import suppress
from pathlib import Path

from module.handler.login import LoginHandler
from module.logger import logger

localization_txt = (
    """
Localization = true
Localization_skin = true
""".strip()
    + "\n"
)


class AzurLaneUncensored(LoginHandler):
    @staticmethod
    def create_level1_uncensored() -> None:
        logger.info("创建本地反和谐文件")
        folder = "./files"
        with suppress(FileNotFoundError):
            shutil.rmtree(folder)
        Path(folder).mkdir(parents=True, exist_ok=True)
        with (Path(folder) / "localization.txt").open("w", encoding="utf-8") as f:
            f.write(localization_txt)

    def run(self) -> None:
        folder = "./toolkit/AzurLaneUncensored"

        logger.hr("生成反和谐文件", level=1)
        Path(folder).mkdir(parents=True, exist_ok=True)
        prev = Path.cwd()

        os.chdir(folder)
        self.create_level1_uncensored()

        logger.hr("推送反和谐文件", level=1)
        remote = f"/sdcard/Android/data/{self.device.package}"
        self.device.adb_push("files", remote)
        logger.info("推送完成")

        os.chdir(prev)
        logger.hr("重启碧蓝航线", level=1)
        self.config.override(Error_HandleError=True)
        self.device.app_stop()
        self.device.app_start()
        self.handle_app_login()

        logger.info("反和谐流程完成")
