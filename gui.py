import argparse
from os import chdir
from pathlib import Path

import uvicorn

from module.logger import configure_file_logging, logger

DEFAULT_WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 22267
PROJECT_ROOT = Path(__file__).resolve().parent


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

    chdir(PROJECT_ROOT)
    configure_file_logging(PROJECT_ROOT, name="gui")
    port = args.port or DEFAULT_WEBUI_PORT

    logger.hr("启动配置")
    logger.attr("Host", DEFAULT_WEBUI_HOST)
    logger.attr("Port", port)
    # CLI 参数校验失败时不加载 WebUI 运行期依赖。
    from module.webui.app import app  # ruff:ignore[import-outside-top-level]

    uvicorn.run(app(auto_run=args.run), host=DEFAULT_WEBUI_HOST, port=port, log_config=None)


if __name__ == "__main__":
    main()
