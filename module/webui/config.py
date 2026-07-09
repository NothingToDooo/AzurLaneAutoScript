from pathlib import Path
from typing import ClassVar

import yaml

from module.base.atomic import atomic_write


class WebUIConfig:
    file: Path
    config: dict[str, str]
    AdbExecutable: str

    CONFIG_FILE = Path("./config/webui.yaml")
    DEFAULTS: ClassVar[dict[str, str]] = {
        "AdbExecutable": "./.venv/Lib/site-packages/adbutils/binaries/adb.exe",
    }

    def __init__(self, file: str | Path = CONFIG_FILE):
        object.__setattr__(self, "file", Path(file))
        object.__setattr__(self, "config", self._read())
        for key, value in self.config.items():
            object.__setattr__(self, key, value)
        if self._read_yaml(self.file) != self.config:
            self.write()

    def __setattr__(self, key: str, value: object) -> None:
        object.__setattr__(self, key, value)
        config = self.__dict__.get("config")
        if key[:1].isupper() and isinstance(config, dict) and key in config and config[key] != value:
            config[key] = value
            self.write()

    def _read_yaml(self, file: Path) -> dict[str, object]:
        try:
            with file.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _read(self) -> dict[str, str]:
        config = self.DEFAULTS.copy()
        data = self._read_yaml(self.file)
        for key in config:
            value = data.get(key)
            if isinstance(value, str) and value:
                config[key] = value
        return config

    def write(self) -> None:
        text = yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False)
        atomic_write(self.file, text)
