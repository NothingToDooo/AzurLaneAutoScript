"""WebUI 进程启动前的导入准备。"""

from module.webui.fake_pil_module import import_fake_pil_module


def prepare_pywebio_imports() -> None:
    """在导入 pywebio 前安装轻量 PIL 占位模块。"""
    import_fake_pil_module()
