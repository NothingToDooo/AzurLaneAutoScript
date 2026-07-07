import os
from pathlib import Path

MOD_DICT = {}
MOD_FUNC_DICT = {}
MOD_CONFIG_DICT = {}


def get_available_func():
    return (
        "Daemon",
        "OpsiDaemon",
        "EventStory",
        "AzurLaneUncensored",
        "Benchmark",
        "GameManager",
    )


def get_available_mod():
    return set(MOD_DICT)


def get_available_mod_func():
    return set(MOD_FUNC_DICT)


def get_func_mod(func):
    return MOD_FUNC_DICT.get(func)


def list_mod_dir():
    return list(MOD_DICT.items())


def get_mod_dir(name):
    return MOD_DICT.get(name)


def get_mod_filepath(name):
    dir_name = get_mod_dir(name)
    if dir_name is None:
        return ""
    return os.path.join("./submodule", dir_name)


def list_mod_template():
    out = []
    for path in Path("./config").iterdir():
        name = path.stem
        extension = path.suffix
        config_name = Path(name).stem
        mod_name = Path(name).suffix
        mod_name = mod_name[1:]
        if config_name == "template" and extension == ".json" and mod_name in MOD_DICT:
            out.append(f"{config_name}-{mod_name}")

    return out


def list_mod_instance():
    MOD_CONFIG_DICT.clear()
    out = []
    for path in Path("./config").iterdir():
        name = path.stem
        extension = path.suffix
        config_name = Path(name).stem
        mod_name = Path(name).suffix
        mod_name = mod_name[1:]
        if config_name != "template" and extension == ".json" and mod_name in MOD_DICT:
            out.append(config_name)
            MOD_CONFIG_DICT[config_name] = mod_name

    return out


def get_config_mod(config_name):
    """
    Args:
        config_name (str):
    """
    if config_name.startswith("template-"):
        mod_name = config_name.replace("template-", "")
        return mod_name if mod_name in MOD_DICT else "alas"
    mod_name = MOD_CONFIG_DICT.get(config_name)
    return mod_name if mod_name in MOD_DICT else "alas"
