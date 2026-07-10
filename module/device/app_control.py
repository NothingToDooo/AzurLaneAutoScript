"""旧应用控制导入的单向兼容层。"""

from module.device.app_service import AppController


class AppControl(AppController):
    """兼容旧类名；不再继承 Connection。"""


__all__ = ["AppControl", "AppController"]
