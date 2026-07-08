from module.webui.app_manage_utils import (
    format_export_config_filename,
    next_alas_instance_name,
    parse_import_config_name,
    validate_new_config_name,
)


def test_parse_import_config_name_uses_plain_json_stem() -> None:
    assert parse_import_config_name("alas.json") == "alas"
    assert parse_import_config_name("daily.extra.json") == "daily.extra"


def test_format_export_config_filename_uses_plain_json_name() -> None:
    assert format_export_config_filename("alas") == "alas.json"
    assert format_export_config_filename("daily") == "daily.json"


def test_next_alas_instance_name_uses_first_available_number() -> None:
    assert next_alas_instance_name(["alas", "alas2", "alas4"]) == "alas3"


def test_next_alas_instance_name_returns_empty_when_full() -> None:
    assert next_alas_instance_name([f"alas{i}" for i in range(2, 100)]) == ""


def test_validate_new_config_name_returns_translation_key() -> None:
    assert validate_new_config_name("alas", ["alas"]) == "Gui.AppManage.NameExist"
    assert validate_new_config_name("bad/name", []) == "Gui.AppManage.InvalidChar"
    assert validate_new_config_name("template2", []) == "Gui.AppManage.InvalidPrefixTemplate"
    assert validate_new_config_name("daily", []) is None
