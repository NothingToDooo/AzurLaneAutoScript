import copy
from pathlib import Path

from deploy.logger import logger
from deploy.utils import DEPLOY_CONFIG, DEPLOY_TEMPLATE, cached_property, poor_yaml_read, poor_yaml_write


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
            (Path(self.root_filepath) / self.config[key])
            .resolve()
            .as_posix()
            .replace('"', '"')
        )

    @cached_property
    def root_filepath(self):
        return Path(__file__).resolve().parents[1].as_posix().replace('"', '"')
