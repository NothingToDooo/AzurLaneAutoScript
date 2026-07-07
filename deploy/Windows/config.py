import copy
import sys
from pathlib import Path
from subprocess import PIPE, TimeoutExpired

import psutil

from deploy.Windows.logger import logger
from deploy.Windows.utils import DEPLOY_CONFIG, DEPLOY_TEMPLATE, cached_property, poor_yaml_read, poor_yaml_write


class ConfigModel:
    # Python 配置
    PythonExecutable: str = "./.venv/Scripts/python.exe"

    # ADB 配置
    AdbExecutable: str = "./.venv/Lib/site-packages/adbutils/binaries/adb.exe"
    ReplaceAdb: bool = True
    AutoConnect: bool = True
    InstallUiautomator2: bool = True

    # 其他配置
    DiscordRichPresence: bool = False

    # WebUI 配置
    WebuiHost: str = "127.0.0.1"
    WebuiPort: int = 22267
    Theme: str = "default"
    DpiScaling: bool = True
    Password: str | None = None
    CDN: str | bool = False
    Run: str | None = None


class DeployConfig(ConfigModel):
    def __init__(self, file=DEPLOY_CONFIG):
        """
        参数：
            file (str)：用户 deploy 配置文件。
        """
        self.file = file
        self.config = {}
        self.config_template = {}
        self.read()

        self.show_config()

    def show_config(self):
        logger.hr("显示 deploy 配置", 1)
        for k, v in self.config.items():
            if k == "Password":
                continue
            if self.config_template.get(k) == v:
                continue
            logger.info(f"{k}: {v}")

        logger.info("其余配置与默认值一致")

    def read(self):
        self.config = poor_yaml_read(DEPLOY_TEMPLATE)
        self.config_template = copy.deepcopy(self.config)
        origin = {key: value for key, value in poor_yaml_read(self.file).items() if key in self.config}
        self.config.update(origin)

        for key, value in self.config.items():
            if hasattr(self, key):
                super().__setattr__(key, value)

        if self.config != origin:
            self.write()

    def write(self):
        poor_yaml_write(self.config, self.file)

    def filepath(self, path):
        """
        参数：
            path (str):

        返回：
            str：绝对路径。
        """
        if Path(path).is_absolute():
            return path

        return (Path(self.root_filepath) / path).resolve().as_posix()

    @cached_property
    def root_filepath(self):
        return Path(__file__).resolve().parents[2].as_posix()

    @cached_property
    def adb(self) -> str:
        exe = self.filepath(self.AdbExecutable)
        if Path(exe).exists():
            return exe

        logger.warning(f"AdbExecutable: {exe} 不存在，改用 `adb`")
        return "adb"

    @cached_property
    def python(self) -> str:
        exe = self.filepath(self.PythonExecutable)
        if Path(exe).exists():
            return exe

        current = sys.executable.replace("\\", "/")
        logger.warning(f"PythonExecutable: {exe} 不存在，改用当前 Python: {current}")
        return current

    def run_command(self, cmd, timeout=10):
        """
        参数：
            cmd (list[str]):
            timeout:

        返回：
            str:
        """
        logger.info(" ".join(cmd))
        process = psutil.Popen(cmd, stdout=PIPE)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.info(f"TimeoutExpired, stdout={stdout}, stderr={stderr}")
        return stdout.decode()
