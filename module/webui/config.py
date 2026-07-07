from pathlib import Path
from typing import Any, ClassVar

import yaml

from module.base.atomic import atomic_write


class WebUIConfig:
    CONFIG_FILE = Path("./config/webui.yaml")
    DEFAULTS: ClassVar[dict[str, Any]] = {
        "AdbExecutable": "./.venv/Lib/site-packages/adbutils/binaries/adb.exe",
        "WebuiHost": "127.0.0.1",
        "WebuiPort": 22267,
        "Theme": "default",
        "Password": None,
        "CDN": False,
        "Run": None,
    }

    def __init__(self, file: str | Path = CONFIG_FILE):
        object.__setattr__(self, "file", Path(file))
        object.__setattr__(self, "config", self._read())
        for key, value in self.config.items():
            object.__setattr__(self, key, value)
        if not self.file.exists():
            self.write()

    def __setattr__(self, key: str, value):
        object.__setattr__(self, key, value)
        config = self.__dict__.get("config")
        if key[:1].isupper() and isinstance(config, dict) and key in config and config[key] != value:
            config[key] = value
            self.write()

    def _read_yaml(self, file: Path) -> dict[str, Any]:
        try:
            with file.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _read(self) -> dict[str, Any]:
        config = self.DEFAULTS.copy()
        data = self._read_yaml(self.file)
        for key in config:
            if key in data:
                config[key] = data[key]
        return config

    def write(self):
        text = yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False)
        atomic_write(self.file, text)
