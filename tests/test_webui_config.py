import yaml

from module.webui.config import WebUIConfig


def test_webui_config_keeps_only_adb_executable(tmp_path) -> None:
    file = tmp_path / "webui.yaml"
    file.write_text(
        (
            "AdbExecutable: C:/platform-tools/adb.exe\n"
            "WebuiHost: 0.0.0.0\n"
            "WebuiPort: 12345\n"
            "Theme: dark\n"
            "Password: old\n"
            "Run: alas"
        ),
        encoding="utf-8",
    )

    config = WebUIConfig(file)

    assert config.AdbExecutable == "C:/platform-tools/adb.exe"
    assert config.config == {"AdbExecutable": "C:/platform-tools/adb.exe"}
    assert not hasattr(config, "Theme")
    assert yaml.safe_load(file.read_text(encoding="utf-8")) == config.config


def test_webui_config_writes_default_adb_executable(tmp_path) -> None:
    file = tmp_path / "webui.yaml"

    config = WebUIConfig(file)

    assert config.AdbExecutable == "./.venv/Lib/site-packages/adbutils/binaries/adb.exe"
    assert yaml.safe_load(file.read_text(encoding="utf-8")) == config.config
