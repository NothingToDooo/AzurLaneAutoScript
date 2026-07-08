def parse_import_config_name(file_name: str) -> tuple[str, str]:
    """
    从导入文件名解析配置名和 mod 名。
    """
    if len(file_name.split(".")) == 2:
        config_name, _ = file_name.split(".")
        return config_name, "alas"
    config_name, mod_name, _ = file_name.rsplit(".", maxsplit=2)
    return config_name, mod_name


def format_export_config_filename(config_name: str, mod_name: str) -> str:
    suffix = "" if mod_name == "alas" else f".{mod_name}"
    return f"{config_name}{suffix}.json"


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
