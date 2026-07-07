from importlib import import_module


def handle_notify(*args, **kwargs):
    # 按需导入 onepush，避免未启用通知时加载第三方推送实现。
    handle_notify = import_module("module.notify.notify").handle_notify
    return handle_notify(*args, **kwargs)
