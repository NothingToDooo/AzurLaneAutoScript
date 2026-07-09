"""
保存固定的国服服务器标识和包名映射。
"""

CN_SERVER = "cn"
CN_PACKAGE = "com.bilibili.azurlane"
CN_ACTIVITY = "com.manjuu.azurlane.MainActivity"


def to_package(package_or_server: str) -> str:
    """
    转换国服标识到固定包名。
    """
    normalized = package_or_server.lower()
    if normalized in {CN_SERVER, CN_PACKAGE}:
        return CN_PACKAGE

    message = f"Package/server invalid for personal CN build: {package_or_server}"
    raise ValueError(message)
