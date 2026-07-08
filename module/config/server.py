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
VALID_SERVER_LIST = {
    "cn_android": [
        "莱茵演习",
        "巴巴罗萨",
        "霸王行动",
        "冰山行动",
        "彩虹计划",
        "发电机计划",
        "瞭望台行动",
        "十字路口行动",
        "朱诺行动",
        "杜立特空袭",
        "地狱犬行动",
        "开罗宣言",
        "奥林匹克行动",
        "小王冠行动",
        "波茨坦公告",
        "白色方案",
        "瓦尔基里行动",
        "曼哈顿计划",
        "八月风暴",
        "秋季旅行",
        "水星行动",
        "莱茵河卫兵",
        "北极光计划",
        "长戟计划",
        "暴雨行动",
        "水仙行动",
        "冬月计划",
        "长弓计划",
        "裁决协议",
    ],
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
