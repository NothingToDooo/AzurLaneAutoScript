"""
保存固定的国服服务器标识和包名映射。

使用 `import module.config.server as server` 导入，不要使用 `from xxx import xxx`。
"""

server = "cn"

VALID_SERVER = ["cn"]
VALID_PACKAGE = {
    "com.bilibili.azurlane": "cn",
}
INVALID_SERVER_MESSAGE = "Server invalid"
DICT_PACKAGE_TO_ACTIVITY = {
    "com.bilibili.azurlane": "com.manjuu.azurlane.MainActivity",
}


def to_server(package_or_server: str) -> str:
    """
    转换包名或服务器名到服务器。

    未知包名按国服处理。
    """
    if package_or_server in VALID_SERVER:
        return package_or_server
    if package_or_server in VALID_PACKAGE:
        return VALID_PACKAGE[package_or_server]
    return "cn"


def to_package(package_or_server: str) -> str:
    """
    转换包名或服务器名到包名。
    """
    package_or_server = package_or_server.lower()
    if package_or_server in VALID_PACKAGE:
        return package_or_server

    for key, value in VALID_PACKAGE.items():
        if value == package_or_server:
            return key

    message = f"{INVALID_SERVER_MESSAGE}: {package_or_server}"
    raise ValueError(message)
