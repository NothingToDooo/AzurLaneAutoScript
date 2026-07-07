import time
from functools import wraps
from json.decoder import JSONDecodeError

import requests
import uiautomator2.exceptions as u2_exc
from adbutils.errors import AdbError
from lxml import etree

from module.device.connection import Connection
from module.device.method.utils import (
    RETRY_TRIES,
    PackageNotInstalled,
    handle_adb_error,
    handle_unknown_host_service,
    retry_sleep,
)
from module.exception import RequestHumanTakeover
from module.logger import logger


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Uiautomator2):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 无法自动处理。
            except RequestHumanTakeover:
                break
            # ADB server 被杀掉。
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
            # uiautomator2 服务偶尔返回非 JSON 内容。
            # json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
            except JSONDecodeError as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()
            # ADB 错误。
            except AdbError as e:
                if handle_adb_error(e):

                    def init():
                        self.adb_reconnect()
                elif handle_unknown_host_service(e):

                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                else:
                    break
            # RuntimeError: USB device 127.0.0.1:5555 is offline
            except RuntimeError as e:
                if handle_adb_error(e):

                    def init():
                        self.adb_reconnect()
                else:
                    break
            # 发生在 `assert c.read string(4) == _OKAY` 中。
            # 模拟器没有启用 ADB。
            except AssertionError as e:
                logger.exception(e)
                break
            # 游戏包未安装。
            except PackageNotInstalled as e:
                logger.error(e)

                def init():
                    self.detect_package()
            # uiautomator2/RPC/HTTP 或本地图像/XML 解析失败时重试。
            except (
                u2_exc.BaseException,
                requests.exceptions.RequestException,
                etree.XMLSyntaxError,
                OSError,
            ) as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()

        logger.critical(f"Retry {func.__name__}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


class Uiautomator2(Connection):
    @retry
    def dump_hierarchy_uiautomator2(self) -> etree._Element:
        content = self.u2.dump_hierarchy(compressed=False)
        # print(content)
        return etree.fromstring(content.encode("utf-8"))

    def uninstall_uiautomator2(self):
        logger.info("Removing uiautomator2")
        for file in [
            "app-uiautomator.apk",
            "app-uiautomator-test.apk",
            "minitouch",
            "minitouch.so",
            "atx-agent",
        ]:
            self.adb_shell(["rm", f"/data/local/tmp/{file}"])
