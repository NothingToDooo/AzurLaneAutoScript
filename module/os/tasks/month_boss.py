import numpy as np

from module.config.utils import get_os_next_reset
from module.logger import logger
from module.os.map import OSMap
from module.os_handler.action_point import OCR_OS_ADAPTABILITY
from module.os_handler.assets import OS_MONTHBOSS_HARD, OS_MONTHBOSS_NORMAL


class OpsiMonthBoss(OSMap):
    def get_adaptability(self):
        return OCR_OS_ADAPTABILITY.ocr(self.device.image)

    def clear_month_boss(self):
        """检查适应性和难度后清理月度首领并维修；行动力不足时抛出 ActionPointLimit，首领耗尽时抛出 TaskEnd。"""
        if self.is_in_opsi_explore():
            logger.info("OpsiExplore is under scheduling, stop OpsiMonthBoss")
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        logger.hr("OS clear Month Boss", level=1)
        logger.hr("Month Boss precheck", level=2)
        self.os_mission_enter()
        logger.attr("OpsiMonthBoss.Mode", self.config.OpsiMonthBoss_Mode)
        if self.appear(OS_MONTHBOSS_NORMAL, offset=(20, 20)):
            logger.attr("Month boss difficulty", "normal")
            is_normal = True
        elif self.appear(OS_MONTHBOSS_HARD, offset=(20, 20)):
            logger.attr("Month boss difficulty", "hard")
            is_normal = False
        else:
            logger.info("No Normal/Hard boss found, stop")
            self.os_mission_quit()
            self.month_boss_delay(is_normal=False, result=False)
            return True
        self.os_mission_quit()

        if not is_normal and self.config.OpsiMonthBoss_Mode == "normal":
            logger.info("Attack normal boss only but having hard boss, skip")
            self.month_boss_delay(is_normal=False, result=True)
            self.config.task_stop()
            return True

        if self.config.OpsiMonthBoss_CheckAdaptability:
            self.os_map_goto_globe(unpin=False)
            adaptability = self.get_adaptability()
            if (np.array(adaptability) < (203, 203, 156)).any():
                logger.info("Adaptability is lower than suppression level, get stronger and come back")
                self.config.task_delay(server_update=True)
                self.config.task_stop()
            # 不需要退出地图，直接复用当前页面。

        logger.hr("Month Boss goto", level=2)
        self.globe_goto(154)
        self.go_month_boss_room(is_normal=is_normal)
        result = self.boss_clear(has_fleet_step=True, is_month=True)

        logger.hr("Month Boss repair", level=2)
        self.fleet_repair(revert=False)
        self.handle_fleet_resolve(revert=False)
        self.month_boss_delay(is_normal=is_normal, result=result)
        return result

    def month_boss_delay(self, is_normal=True, result=True):
        """按普通或困难模式及清理结果安排下次运行。"""
        if is_normal:
            if result:
                if self.config.OpsiMonthBoss_Mode == "normal_hard":
                    logger.info("Monthly boss normal cleared, run hard boss then")
                    self.config.task_stop()
                else:
                    logger.info("Monthly boss normal cleared, task stop")
                    next_reset = get_os_next_reset()
                    self.config.task_delay(target=next_reset)
                    self.config.task_stop()
            else:
                logger.info("Unable to clear the normal monthly boss, will try later")
                self.config.opsi_task_delay(recon_scan=False, submarine_call=True, ap_limit=False)
                self.config.task_stop()
        elif result:
            logger.info("Monthly boss hard cleared, task stop")
            next_reset = get_os_next_reset()
            self.config.task_delay(target=next_reset)
            self.config.task_stop()
        else:
            logger.info("Unable to clear the hard monthly boss, try again on tomorrow")
            self.config.task_delay(server_update=True)
            self.config.task_stop()
