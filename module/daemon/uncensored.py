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
    def create_level1_uncensored(self):
        logger.info("创建本地反和谐文件")
        folder = "./files"
        with suppress(FileNotFoundError):
            shutil.rmtree(folder)
        Path(folder).mkdir(parents=True, exist_ok=True)
        with open(Path(folder) / "localization.txt", "w", encoding="utf-8") as f:
            f.write(localization_txt)

    def run(self):
        """
        执行本地反和谐流程：

        1. 生成本地反和谐文件。
        2. 推送文件到模拟器。
        3. 重启游戏。
        """
        folder = "./toolkit/AzurLaneUncensored"

        logger.hr("生成反和谐文件", level=1)
        Path(folder).mkdir(parents=True, exist_ok=True)
        prev = Path.cwd()

        # 在 ./toolkit/AzurLaneUncensored 中生成推送目录。
        os.chdir(folder)
        self.create_level1_uncensored()

        logger.hr("推送反和谐文件", level=1)
        command = ["push", "files", f"/sdcard/Android/data/{self.device.package}"]
        logger.info(f"命令: {command}")
        self.device.adb_command(command, timeout=30)
        logger.info("推送完成")

        # 回到项目根目录。
        os.chdir(prev)
        logger.hr("重启碧蓝航线", level=1)
        self.config.override(Error_HandleError=True)
        self.device.app_stop()
        self.device.app_start()
        self.handle_app_login()

        logger.info("反和谐流程完成")


if __name__ == "__main__":
    AzurLaneUncensored("alas", task="AzurLaneUncensored").run()
