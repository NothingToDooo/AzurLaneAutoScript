import argparse

import uvicorn

from module.logger import logger
from module.webui.setting import State


def func() -> None:
    parser = argparse.ArgumentParser(description="Alas WebUI 服务")
    parser.add_argument(
        "--host",
        type=str,
        help="监听地址，默认使用 WebUI 配置里的 WebuiHost。",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="监听端口，默认使用 WebUI 配置里的 WebuiPort。",
    )
    parser.add_argument("-k", "--key", type=str, help="WebUI 密码，默认不启用。")
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="使用 jsdelivr 加载 pywebio 静态文件，默认本地提供。",
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="启动时自动运行指定配置。",
    )
    args, _ = parser.parse_known_args()

    host = args.host or State.webui_config.WebuiHost or "127.0.0.1"
    port = args.port or int(State.webui_config.WebuiPort) or 22267

    logger.hr("启动配置")
    logger.attr("Host", host)
    logger.attr("Port", port)
    uvicorn.run("module.webui.app:app", host=host, port=port, factory=True)


if __name__ == "__main__":
    func()
