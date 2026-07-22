import pytest

from module.config.server import CN_PACKAGE
from module.device import app_package as app_package_module
from module.device.app_package import AppPackage
from module.exception import HumanTakeoverRequiredError


class _Logger:
    def __init__(self) -> None:
        self.criticals: list[str] = []
        self.infos: list[str] = []
        self.headers: list[str] = []
        self.attrs: list[tuple[str, str]] = []

    def critical(self, message: str) -> None:
        self.criticals.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)

    def hr(self, message: str) -> None:
        self.headers.append(message)

    def attr(self, name: str, value: str) -> None:
        self.attrs.append((name, value))


class _PackageDevice(AppPackage):
    def __init__(self, packages: list[str]) -> None:
        self.serial = "127.0.0.1:16384"
        self.packages = packages

    def list_package(self, *, show_log: bool = True) -> list[str]:
        del show_log
        return self.packages


def test_list_known_packages_keeps_only_fixed_cn_package() -> None:
    connection = _PackageDevice([CN_PACKAGE, "com.example.other"])

    assert connection.list_known_packages(show_log=False) == [CN_PACKAGE]


def test_ensure_package_installed_accepts_fixed_cn_package() -> None:
    connection = _PackageDevice([CN_PACKAGE])

    connection.ensure_package_installed()


def test_ensure_package_installed_rejects_missing_cn_package(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _Logger()
    monkeypatch.setattr(app_package_module, "logger", logger)
    connection = _PackageDevice(["com.example.other"])

    with pytest.raises(HumanTakeoverRequiredError):
        connection.ensure_package_installed()

    assert logger.criticals == [
        '未在设备 "127.0.0.1:16384" 上找到国服客户端包名 "com.bilibili.azurlane"，请确认碧蓝航线国服已安装'
    ]


def test_confirm_fixed_package_uses_fixed_cn_package(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _Logger()
    monkeypatch.setattr(app_package_module, "logger", logger)
    connection = _PackageDevice([CN_PACKAGE])

    connection.confirm_fixed_package()

    assert connection.package == CN_PACKAGE
    assert logger.attrs == [("PackageName", CN_PACKAGE)]


def test_detect_package_uses_fixed_cn_package(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _Logger()
    monkeypatch.setattr(app_package_module, "logger", logger)
    connection = _PackageDevice([CN_PACKAGE])

    connection.detect_package()

    assert connection.package == CN_PACKAGE
    assert logger.headers == ["Check package"]
    assert logger.attrs == [("PackageName", CN_PACKAGE)]
    assert logger.infos == ['找到固定国服客户端包名 "com.bilibili.azurlane"']
