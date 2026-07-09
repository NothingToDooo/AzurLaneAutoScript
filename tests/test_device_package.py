import pytest

from module.config.server import CN_PACKAGE
from module.device import connection as connection_module
from module.device.connection import Connection
from module.exception import RequestHumanTakeover


class _Logger:
    def __init__(self) -> None:
        self.criticals: list[str] = []
        self.infos: list[str] = []
        self.headers: list[str] = []

    def critical(self, message: str) -> None:
        self.criticals.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)

    def hr(self, message: str) -> None:
        self.headers.append(message)


class _PackageConnection(Connection):
    def __init__(self, packages: list[str]) -> None:
        self.serial = "127.0.0.1:16384"
        self.packages = packages

    def list_package(self, show_log=True):
        del show_log
        return self.packages


def test_list_known_packages_keeps_only_fixed_cn_package() -> None:
    connection = _PackageConnection([CN_PACKAGE, "com.example.other"])

    assert connection.list_known_packages(show_log=False) == [CN_PACKAGE]


def test_ensure_package_installed_accepts_fixed_cn_package() -> None:
    connection = _PackageConnection([CN_PACKAGE])

    connection.ensure_package_installed()


def test_ensure_package_installed_rejects_missing_cn_package(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _Logger()
    monkeypatch.setattr(connection_module, "logger", logger)
    connection = _PackageConnection(["com.example.other"])

    with pytest.raises(RequestHumanTakeover):
        connection.ensure_package_installed()

    assert logger.criticals == [
        '未在设备 "127.0.0.1:16384" 上找到国服客户端包名 "com.bilibili.azurlane"，请确认碧蓝航线国服已安装'
    ]


def test_detect_package_uses_fixed_cn_package(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _Logger()
    monkeypatch.setattr(connection_module, "logger", logger)
    connection = _PackageConnection([CN_PACKAGE])

    connection.detect_package()

    assert connection.package == CN_PACKAGE
    assert logger.headers == ["Check package"]
    assert logger.infos == ['找到固定国服客户端包名 "com.bilibili.azurlane"']
