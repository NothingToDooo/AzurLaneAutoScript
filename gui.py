import argparse

import uvicorn

from module.logger import logger

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
    parser.add_argument(
        "--run",
        action="store_true",
        help="启动时自动运行 alas。",
    )
    args = parser.parse_args()

    port = args.port or DEFAULT_WEBUI_PORT

    logger.hr("启动配置")
    logger.attr("Host", DEFAULT_WEBUI_HOST)
    logger.attr("Port", port)
    from module.webui.app import app  # noqa: PLC0415

    uvicorn.run(app(auto_run=args.run), host=DEFAULT_WEBUI_HOST, port=port, log_config=None)


if __name__ == "__main__":
    main()
