import copy
import os
import subprocess
import sys
from pathlib import Path

from deploy.Windows.logger import logger
from deploy.Windows.utils import DEPLOY_CONFIG, DEPLOY_TEMPLATE, cached_property, poor_yaml_read, poor_yaml_write


class ExecutionError(Exception):
    pass


class ConfigModel:
    # Python 配置
    PythonExecutable: str = "./.venv/Scripts/python.exe"

    # ADB 配置
    AdbExecutable: str = "./.venv/Lib/site-packages/adbutils/binaries/adb.exe"
    ReplaceAdb: bool = True
    AutoConnect: bool = True
    InstallUiautomator2: bool = True

    # OCR 配置
    UseOcrServer: bool = False
    StartOcrServer: bool = False
    OcrServerPort: int = 22268
    OcrClientAddress: str = "127.0.0.1:22268"

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

    def execute(self, command, allow_failure=False, output=True):
        """
        参数：
            command (str):
            allow_failure (bool):
            output(bool):

        返回：
            bool：是否成功。
        """
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        if not output:
            command = command + " >nul 2>nul"
        logger.info(command)
        error_code = os.system(command)
        if error_code:
            if allow_failure:
                logger.info(f"[允许失败]，error_code: {error_code}")
                return False
            logger.info(f"[失败]，error_code: {error_code}")
            self.show_error(command)
            raise ExecutionError
        logger.info("[成功]")
        return True

    def subprocess_execute(self, cmd, timeout=10):
        """
        参数：
            cmd (list[str]):
            timeout:

        返回：
            str:
        """
        logger.info(" ".join(cmd))
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            process.kill()
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.info(f"TimeoutExpired, stdout={stdout}, stderr={stderr}")
        return stdout.decode()

    def show_error(self, command=None):
        logger.hr("命令执行失败", 0)
        self.show_config()
        logger.info("")
        logger.info(f"最后执行的命令: {command}")
        logger.info("请检查 config/deploy.yaml 中的 deploy 配置")
        logger.info("如果需要排查，请保留完整窗口截图")
