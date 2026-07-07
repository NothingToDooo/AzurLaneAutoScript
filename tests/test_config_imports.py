import importlib


def test_config_module_imports() -> None:
    module = importlib.import_module("module.config.config")

    assert hasattr(module, "AzurLaneConfig")
