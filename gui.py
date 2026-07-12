import argparse

import uvicorn

from module.logger import logger
from module.webui.bootstrap import prepare_pywebio_imports

DEFAULT_WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 22267


def main() -> None:
    parser = argparse.ArgumentParser(description="Alas WebUI 服务")
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help=f"监听端口，默认 {DEFAULT_WEBUI_PORT}。",
    )
    parser.add_argument("-k", "--key", type=str, help="WebUI 密码，默认不启用。")
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="启动时自动运行指定配置。",
    )
    args = parser.parse_args()

    port = args.port or DEFAULT_WEBUI_PORT

    logger.hr("启动配置")
    logger.attr("Host", DEFAULT_WEBUI_HOST)
    logger.attr("Port", port)
    prepare_pywebio_imports()
    uvicorn.run("module.webui.app:app", host=DEFAULT_WEBUI_HOST, port=port, factory=True, log_config=None)


if __name__ == "__main__":
    main()
