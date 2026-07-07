import re
import sys
import time
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import inflection

from module.base.decorator import cached_property, del_cached_property
from module.base.resource import release_resources
from module.config.config import AzurLaneConfig, TaskEnd
from module.config.deep import deep_get, deep_set
from module.exception import (
    GameBugError,
    GameNotRunningError,
    GamePageUnknownError,
    GameStuckError,
    GameTooManyClickError,
    RequestHumanTakeover,
    ScriptError,
)
from module.logger import logger
from module.notify import handle_notify
from module.task_registry import get_task_spec

if TYPE_CHECKING:
    import threading


def _load_attr(module_name: str, attr_name: str):
    """按需加载重模块里的对象。"""
    module = import_module(module_name)
    return getattr(module, attr_name)


class AzurLaneAutoScript:
    stop_event: threading.Event | None = None

    def __init__(self, config_name: str = "alas") -> None:
        logger.hr("Start", level=0)
        self.config_name = config_name
        # 跳过第一次重启。
        self.is_first_task = True
        # 记录任务失败次数。
        # key 为任务名，value 为失败次数。
        self.failure_record = {}

    @cached_property
    def config(self):
        try:
            return AzurLaneConfig(config_name=self.config_name)
        except RequestHumanTakeover:
            logger.critical("Request human takeover")
            sys.exit(1)

    @cached_property
    def device(self):
        try:
            Device = _load_attr("module.device.device", "Device")
            return Device(config=self.config)
        except RequestHumanTakeover:
            logger.critical("Request human takeover")
            sys.exit(1)

    @cached_property
    def checker(self):
        ServerChecker = _load_attr("module.server_checker", "ServerChecker")
        return ServerChecker(server=self.config.Emulator_ServerName)

    def run(self, command: str, skip_first_screenshot: bool = False) -> bool:
        try:
            if not skip_first_screenshot:
                self.device.screenshot()
            task_spec = get_task_spec(command)
            if task_spec is not None:
                task_spec.execute(self)
            else:
                self.__getattribute__(command)()
        except TaskEnd:
            return True
        except GameNotRunningError as e:
            logger.warning(e)
            self.config.task_call("Restart")
            return False
        except (GameStuckError, GameTooManyClickError) as e:
            logger.error(e)
            self.save_error_log()
            logger.warning(f"Game stuck, {self.device.package} will be restarted in 10 seconds")
            logger.warning("If you are playing by hand, please stop Alas")
            self.config.task_call("Restart")
            self.device.sleep(10)
            return False
        except GameBugError as e:
            logger.warning(e)
            self.save_error_log()
            logger.warning("An error has occurred in Azur Lane game client, Alas is unable to handle")
            logger.warning(f"Restarting {self.device.package} to fix it")
            self.config.task_call("Restart")
            self.device.sleep(10)
            return False
        except GamePageUnknownError:
            logger.info("Game server may be under maintenance or network may be broken, check server status now")
            self.checker.check_now()
            if self.checker.is_available():
                logger.critical("Game page unknown")
                self.save_error_log()
                handle_notify(
                    self.config.Error_OnePushConfig,
                    title=f"Alas <{self.config_name}> crashed",
                    content=f"<{self.config_name}> GamePageUnknownError",
                )
                sys.exit(1)
            else:
                self.checker.wait_until_available()
                return False
        except ScriptError as e:
            logger.exception(e)
            logger.critical("This is likely to be a mistake of developers, but sometimes just random issues")
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"Alas <{self.config_name}> crashed",
                content=f"<{self.config_name}> ScriptError",
            )
            sys.exit(1)
        except RequestHumanTakeover:
            logger.critical("Request human takeover")
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"Alas <{self.config_name}> crashed",
                content=f"<{self.config_name}> RequestHumanTakeover",
            )
            sys.exit(1)
        # 任务崩溃边界：保存现场、通知并退出，避免调度循环继续运行在未知状态。
        except Exception as e:  # noqa: BLE001
            logger.exception(e)
            self.save_error_log()
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"Alas <{self.config_name}> crashed",
                content=f"<{self.config_name}> Exception occurred",
            )
            sys.exit(1)
        else:
            return True

    def save_error_log(self) -> None:
        """保存最近 60 张截图，并把当前日志写入错误目录。"""
        save_image = _load_attr("module.base.utils", "save_image")
        handle_sensitive_image = _load_attr("module.handler.sensitive_info", "handle_sensitive_image")
        handle_sensitive_logs = _load_attr("module.handler.sensitive_info", "handle_sensitive_logs")

        if self.config.Error_SaveError:
            error_dir = Path("./log/error")
            error_dir.mkdir(exist_ok=True)
            folder = error_dir / str(int(time.time() * 1000))
            logger.warning(f"Saving error: {folder}")
            folder.mkdir()
            for data in self.device.screenshot_deque:
                image_time = datetime.strftime(data["time"], "%Y-%m-%d_%H-%M-%S-%f")
                image = handle_sensitive_image(data["image"])
                save_image(image, str(folder / f"{image_time}.png"))
            with Path(logger.log_file).open(encoding="utf-8") as f:
                lines = f.readlines()
                start = 0
                for index, raw_line in enumerate(lines):
                    line = raw_line.strip(" \r\t\n")
                    if re.match(r"^═{15,}$", line):
                        start = index
                lines = lines[start - 2 :]
                lines = handle_sensitive_logs(lines)
            with (folder / "log.txt").open("w", encoding="utf-8") as f:
                f.writelines(lines)

    def restart(self) -> None:
        LoginHandler = _load_attr("module.handler.login", "LoginHandler")
        LoginHandler(self.config, device=self.device).app_restart()

    def start(self) -> None:
        LoginHandler = _load_attr("module.handler.login", "LoginHandler")
        LoginHandler(self.config, device=self.device).app_start()

    def goto_main(self) -> None:
        LoginHandler = _load_attr("module.handler.login", "LoginHandler")
        UI = _load_attr("module.ui.ui", "UI")

        if self.device.app_is_running():
            logger.info("App is already running, goto main page")
            UI(self.config, device=self.device).ui_goto_main()
        else:
            logger.info("App is not running, start app and goto main page")
            LoginHandler(self.config, device=self.device).app_start()
            UI(self.config, device=self.device).ui_goto_main()

    def wait_until(self, future: datetime) -> bool:
        """等待到指定时间；如果配置变化则提前返回。"""
        future += timedelta(seconds=1)
        self.config.start_watching()
        while 1:
            if datetime.now() > future:
                return True
            if self.stop_event is not None and self.stop_event.is_set():
                logger.info("Update event detected")
                logger.info(f"[{self.config_name}] exited. Reason: Update")
                sys.exit(0)

            time.sleep(5)

            if self.config.should_reload():
                return False
        return False

    def get_next_task(self) -> str:
        """返回下一个任务名称。"""
        while 1:
            task = self.config.get_next()
            self.config.task = task
            self.config.bind(task)

            if self.config.task.command != "Alas":
                release_resources(next_task=task.command)

            if task.next_run > datetime.now():
                logger.info(f"Wait until {task.next_run} for task `{task.command}`")
                self.is_first_task = False
                method = self.config.Optimization_WhenTaskQueueEmpty
                if method == "close_game":
                    logger.info("Close game during wait")
                    self.device.app_stop()
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, "config")
                        continue
                    if task.command != "Restart":
                        self.config.task_call("Restart")
                        del_cached_property(self, "config")
                        continue
                elif method == "goto_main":
                    logger.info("Goto main page during wait")
                    self.run("goto_main")
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, "config")
                        continue
                elif method == "stay_there":
                    logger.info("Stay there during wait")
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, "config")
                        continue
                else:
                    logger.warning(f"Invalid Optimization_WhenTaskQueueEmpty: {method}, fallback to stay_there")
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, "config")
                        continue
            break

        AzurLaneConfig.is_hoarding_task = False
        return task.command

    def loop(self) -> None:
        logger.set_file_logger(self.config_name)
        logger.info(f"Start scheduler loop: {self.config_name}")

        while 1:
            # 检查来自 WebUI 的更新事件。
            if self.stop_event is not None and self.stop_event.is_set():
                logger.info("Update event detected")
                logger.info(f"Alas [{self.config_name}] exited.")
                break
            # 检查游戏服务器维护状态。
            self.checker.wait_until_available()
            if self.checker.is_recovered():
                # 有个很难复现的偶发问题：
                # 配置变化后可能因为阻塞没能及时更新，所以恢复后主动刷新一次。
                del_cached_property(self, "config")
                logger.info("Server or network is recovered. Restart game client")
                self.config.task_call("Restart")
            # 获取任务。
            task = self.get_next_task()
            # 初始化设备并切换服务器配置。
            _ = self.device
            self.device.config = self.config
            # 跳过第一次重启。
            if self.is_first_task and task == "Restart":
                logger.info("Skip task `Restart` at scheduler start")
                self.config.task_delay(server_update=True)
                del_cached_property(self, "config")
                continue

            # 运行任务。
            logger.info(f"Scheduler: Start task `{task}`")
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            logger.hr(task, level=0)
            success = self.run(inflection.underscore(task))
            logger.info(f"Scheduler: End task `{task}`")
            self.is_first_task = False

            # 检查失败次数。
            failed = deep_get(self.failure_record, keys=task, default=0)
            failed = 0 if success else failed + 1
            deep_set(self.failure_record, keys=task, value=failed)
            if failed >= 3:
                logger.critical(f"Task `{task}` failed 3 or more times.")
                logger.critical(
                    "Possible reason #1: You haven't used it correctly. Please read the help text of the options.",
                )
                logger.critical(
                    "Possible reason #2: There is a problem with this task. "
                    "Please contact developers or try to fix it yourself.",
                )
                logger.critical("Request human takeover")
                handle_notify(
                    self.config.Error_OnePushConfig,
                    title=f"Alas <{self.config_name}> crashed",
                    content=f"<{self.config_name}> RequestHumanTakeover\nTask `{task}` failed 3 or more times.",
                )
                sys.exit(1)

            if success:
                del_cached_property(self, "config")
                continue
            if self.config.Error_HandleError:
                # self.config.task_delay(success=False)
                del_cached_property(self, "config")
                self.checker.check_now()
                continue
            break


if __name__ == "__main__":
    alas = AzurLaneAutoScript()
    alas.loop()
