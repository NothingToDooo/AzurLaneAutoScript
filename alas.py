import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import inflection

from module.base.decorator import cached_property, del_cached_property
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

if TYPE_CHECKING:
    import threading


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
        except Exception as e:
            logger.exception(e)
            sys.exit(1)

    @cached_property
    def device(self):
        try:
            from module.device.device import Device

            return Device(config=self.config)
        except RequestHumanTakeover:
            logger.critical("Request human takeover")
            sys.exit(1)
        except Exception as e:
            logger.exception(e)
            sys.exit(1)

    @cached_property
    def checker(self):
        try:
            from module.server_checker import ServerChecker

            return ServerChecker(server=self.config.Emulator_ServerName)
        except Exception as e:
            logger.exception(e)
            sys.exit(1)

    def run(self, command: str, skip_first_screenshot: bool = False) -> bool:
        try:
            if not skip_first_screenshot:
                self.device.screenshot()
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
        except Exception as e:
            logger.exception(e)
            self.save_error_log()
            handle_notify(
                self.config.Error_OnePushConfig,
                title=f"Alas <{self.config_name}> crashed",
                content=f"<{self.config_name}> Exception occured",
            )
            sys.exit(1)
        else:
            return True

    def save_error_log(self) -> None:
        """保存最近 60 张截图，并把当前日志写入错误目录。"""
        from module.base.utils import save_image
        from module.handler.sensitive_info import handle_sensitive_image, handle_sensitive_logs

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
        from module.handler.login import LoginHandler

        LoginHandler(self.config, device=self.device).app_restart()

    def start(self) -> None:
        from module.handler.login import LoginHandler

        LoginHandler(self.config, device=self.device).app_start()

    def goto_main(self) -> None:
        from module.handler.login import LoginHandler
        from module.ui.ui import UI

        if self.device.app_is_running():
            logger.info("App is already running, goto main page")
            UI(self.config, device=self.device).ui_goto_main()
        else:
            logger.info("App is not running, start app and goto main page")
            LoginHandler(self.config, device=self.device).app_start()
            UI(self.config, device=self.device).ui_goto_main()

    def research(self) -> None:
        from module.research.research import RewardResearch

        RewardResearch(config=self.config, device=self.device).run()

    def commission(self) -> None:
        from module.commission.commission import RewardCommission

        RewardCommission(config=self.config, device=self.device).run()

    def tactical(self) -> None:
        from module.tactical.tactical_class import RewardTacticalClass

        RewardTacticalClass(config=self.config, device=self.device).run()

    def dorm(self) -> None:
        from module.dorm.dorm import RewardDorm

        RewardDorm(config=self.config, device=self.device).run()

    def meowfficer(self) -> None:
        from module.meowfficer.meowfficer import RewardMeowfficer

        RewardMeowfficer(config=self.config, device=self.device).run()

    def guild(self) -> None:
        from module.guild.guild_reward import RewardGuild

        RewardGuild(config=self.config, device=self.device).run()

    def reward(self) -> None:
        from module.reward.reward import Reward

        Reward(config=self.config, device=self.device).run()

    def awaken(self) -> None:
        from module.awaken.awaken import Awaken

        Awaken(config=self.config, device=self.device).run()

    def shop_frequent(self) -> None:
        from module.shop.shop_reward import RewardShop

        RewardShop(config=self.config, device=self.device).run_frequent()

    def shop_once(self) -> None:
        from module.shop.shop_reward import RewardShop

        RewardShop(config=self.config, device=self.device).run_once()

    def shipyard(self) -> None:
        from module.shipyard.shipyard_reward import RewardShipyard

        RewardShipyard(config=self.config, device=self.device).run()

    def gacha(self) -> None:
        from module.gacha.gacha_reward import RewardGacha

        RewardGacha(config=self.config, device=self.device).run()

    def freebies(self) -> None:
        from module.freebies.freebies import Freebies

        Freebies(config=self.config, device=self.device).run()

    def minigame(self) -> None:
        from module.minigame.minigame import Minigame

        Minigame(config=self.config, device=self.device).run()

    def private_quarters(self) -> None:
        from module.private_quarters.private_quarters import PrivateQuarters

        PrivateQuarters(config=self.config, device=self.device).run()

    def daily(self) -> None:
        from module.daily.daily import Daily

        Daily(config=self.config, device=self.device).run()

    def hard(self) -> None:
        from module.hard.hard import CampaignHard

        CampaignHard(config=self.config, device=self.device).run()

    def exercise(self) -> None:
        from module.exercise.exercise import Exercise

        Exercise(config=self.config, device=self.device).run()

    def sos(self) -> None:
        from module.sos.sos import CampaignSos

        CampaignSos(config=self.config, device=self.device).run()

    def war_archives(self) -> None:
        from module.war_archives.war_archives import CampaignWarArchives

        CampaignWarArchives(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def raid_daily(self) -> None:
        from module.raid.daily import RaidDaily

        RaidDaily(config=self.config, device=self.device).run()

    def event_a(self) -> None:
        from module.event.campaign_abcd import CampaignABCD

        CampaignABCD(config=self.config, device=self.device).run()

    def event_b(self) -> None:
        from module.event.campaign_abcd import CampaignABCD

        CampaignABCD(config=self.config, device=self.device).run()

    def event_c(self) -> None:
        from module.event.campaign_abcd import CampaignABCD

        CampaignABCD(config=self.config, device=self.device).run()

    def event_d(self) -> None:
        from module.event.campaign_abcd import CampaignABCD

        CampaignABCD(config=self.config, device=self.device).run()

    def event_sp(self) -> None:
        from module.event.campaign_sp import CampaignSP

        CampaignSP(config=self.config, device=self.device).run()

    def maritime_escort(self) -> None:
        from module.event.maritime_escort import MaritimeEscort

        MaritimeEscort(config=self.config, device=self.device).run()

    def opsi_ash_assist(self) -> None:
        from module.os_ash.meta import AshBeaconAssist

        AshBeaconAssist(config=self.config, device=self.device).run()

    def opsi_ash_beacon(self) -> None:
        from module.os_ash.meta import OpsiAshBeacon

        OpsiAshBeacon(config=self.config, device=self.device).run()

    def opsi_explore(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_explore()

    def opsi_shop(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_shop()

    def opsi_voucher(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_voucher()

    def opsi_daily(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_daily()

    def opsi_obscure(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_obscure()

    def opsi_month_boss(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_month_boss()

    def opsi_abyssal(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_abyssal()

    def opsi_archive(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_archive()

    def opsi_stronghold(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_stronghold()

    def opsi_meowfficer_farming(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_meowfficer_farming()

    def opsi_hazard1_leveling(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_hazard1_leveling()

    def opsi_cross_month(self) -> None:
        from module.campaign.os_run import OSCampaignRun

        OSCampaignRun(config=self.config, device=self.device).opsi_cross_month()

    def main(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def main2(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def main3(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def event(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def event2(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def raid(self) -> None:
        from module.raid.run import RaidRun

        RaidRun(config=self.config, device=self.device).run()

    def hospital(self) -> None:
        from module.event_hospital.hospital import Hospital

        Hospital(config=self.config, device=self.device).run()

    def coalition(self) -> None:
        from module.coalition.coalition import Coalition

        Coalition(config=self.config, device=self.device).run()

    def coalition_sp(self) -> None:
        from module.coalition.coalition_sp import CoalitionSP

        CoalitionSP(config=self.config, device=self.device).run()

    def c72_mystery_farming(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def c122_medium_leveling(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def c124_large_leveling(self) -> None:
        from module.campaign.run import CampaignRun

        CampaignRun(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def gems_farming(self) -> None:
        from module.campaign.gems_farming import GemsFarming

        GemsFarming(config=self.config, device=self.device).run(
            name=self.config.Campaign_Name,
            folder=self.config.Campaign_Event,
            mode=self.config.Campaign_Mode,
        )

    def daemon(self) -> None:
        from module.daemon.daemon import AzurLaneDaemon

        AzurLaneDaemon(config=self.config, device=self.device, task="Daemon").run()

    def opsi_daemon(self) -> None:
        from module.daemon.os_daemon import AzurLaneDaemon

        AzurLaneDaemon(config=self.config, device=self.device, task="OpsiDaemon").run()

    def event_story(self) -> None:
        from module.eventstory.eventstory import EventStory

        EventStory(config=self.config, device=self.device, task="EventStory").run()

    def azur_lane_uncensored(self) -> None:
        from module.daemon.uncensored import AzurLaneUncensored

        AzurLaneUncensored(config=self.config, device=self.device, task="AzurLaneUncensored").run()

    def benchmark(self) -> None:
        from module.daemon.benchmark import run_benchmark

        run_benchmark(config=self.config)

    def game_manager(self) -> None:
        from module.daemon.game_manager import GameManager

        GameManager(config=self.config, device=self.device, task="GameManager").run()

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

            from module.base.resource import release_resources

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
