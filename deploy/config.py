import copy
from typing import Optional, Union

from deploy.logger import logger
from deploy.utils import *


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
    Password: Optional[str] = None
    CDN: Union[str, bool] = False
    Run: Optional[str] = None


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
        """
        读取并更新 deploy 配置，然后复制到属性上。
        """
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

    def filepath(self, key):
        """
        参数：
            key (str):

        返回：
            str：绝对路径。
        """
        return (
            os.path.abspath(os.path.join(self.root_filepath, self.config[key]))
            .replace(r"\\", "/")
            .replace("\\", "/")
            .replace('"', '"')
        )

    @cached_property
    def root_filepath(self):
        return (
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
            .replace(r"\\", "/")
            .replace("\\", "/")
            .replace('"', '"')
        )

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
            else:
                logger.info(f"[失败]，error_code: {error_code}")
                self.show_error(command)
                raise ExecutionError
        else:
            logger.info("[成功]")
            return True

    def show_error(self, command=None):
        logger.hr("命令执行失败", 0)
        self.show_config()
        logger.info("")
        logger.info(f"最后执行的命令: {command}")
        logger.info("请检查 config/deploy.yaml 中的 deploy 配置")
        logger.info("如果需要排查，请保留完整窗口截图")
