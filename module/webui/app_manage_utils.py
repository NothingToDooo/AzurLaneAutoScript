from pathlib import Path


def parse_import_config_name(file_name: str) -> str:
    """
    从导入文件名解析配置名。
    """
    return Path(file_name).stem


def format_export_config_filename(config_name: str) -> str:
    return f"{config_name}.json"


def next_alas_instance_name(existing_names: list[str]) -> str:
    for i in range(2, 100):
        if f"alas{i}" not in existing_names:
            return f"alas{i}"
    return ""


def validate_new_config_name(config_name: str, existing_names: list[str]) -> str | None:
    if config_name in existing_names:
        return "Gui.AppManage.NameExist"
    if set(config_name) & set(".\\/:*?\"'<>|"):
        return "Gui.AppManage.InvalidChar"
    if config_name.lower().startswith("template"):
        return "Gui.AppManage.InvalidPrefixTemplate"
    return None
