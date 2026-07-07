from module.base.timer import Timer
from module.combat.combat import Combat
from module.logger import logger
from module.meta_reward import assets as mr_assets
from module.os_ash.assets import DOSSIER_LIST
from module.ui.page import page_meta
from module.ui.ui import UI


class BeaconReward(Combat, UI):
    def meta_reward_notice_appear(self):
        """返回 META 奖励红点是否出现。"""
        return self.appear(mr_assets.META_REWARD_NOTICE, threshold=30)

    def meta_reward_receive(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Returns:
            bool: If received.

        Pages:
            in: page_meta or REWARD_CHECK
            out: REWARD_CHECK
        """
        logger.hr("Meta reward receive", level=1)
        confirm_timer = Timer(1, count=3).start()
        received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束：REWARD_CHECK 出现且 REWARD_RECEIVE 变灰。
            if self.appear(mr_assets.REWARD_CHECK, offset=(20, 20)) and self.image_color_count(
                mr_assets.REWARD_RECEIVE, color=(49, 52, 49), threshold=221, count=400
            ):
                break

            if self.appear_then_click(mr_assets.REWARD_ENTER, offset=(20, 20), interval=3):
                continue
            if self.match_template_color(mr_assets.REWARD_RECEIVE, offset=(20, 20), interval=3):
                self.device.click(mr_assets.REWARD_RECEIVE)
                confirm_timer.reset()
                continue
            if self.handle_popup_confirm("META_REWARD"):
                # 锁定新的 META 舰船。
                confirm_timer.reset()
                continue
            if self.handle_get_items():
                received = True
                confirm_timer.reset()
                continue
            if self.handle_get_ship():
                received = True
                confirm_timer.reset()
                continue

        logger.info(f"Meta reward receive finished, received={received}")
        return received

    def meta_sync_notice_appear(self, interval=0):
        """返回同步奖励入口是否出现。"""
        return self.appear(mr_assets.SYNC_REWARD_NOTICE, threshold=30, interval=interval) or self.appear(
            mr_assets.SYNC_TAP, threshold=30, interval=interval
        )

    def meta_sync_receive(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Returns:
            bool: If received.

        Pages:
            in: SYNC_ENTER
            out: SYNC_ENTER if meta ship synced < 100%
                REWARD_ENTER if meta ship synced >= 100%
        """
        logger.hr("Meta sync receive", level=1)
        received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束：同步进度达到 100%。
            if self.appear(mr_assets.REWARD_ENTER, offset=(20, 20)):
                logger.info("meta_sync_receive ends at REWARD_ENTER")
                break

            if self.appear(mr_assets.SYNC_ENTER, offset=(20, 20)):
                if not self.meta_sync_notice_appear():
                    logger.info("meta_sync_receive ends at SYNC_ENTER")
                    break

            # 点击领取。
            if self.handle_popup_confirm("META_REWARD"):
                # 锁定新的 META 舰船。
                continue
            if self.handle_get_items():
                received = True
                continue
            if self.handle_get_ship():
                received = True
                continue
            if self.appear(mr_assets.SYNC_REWARD_NOTICE, threshold=30, interval=3):
                logger.info(f"sync reward notice appear -> {mr_assets.SYNC_ENTER}")
                self.device.click(mr_assets.SYNC_ENTER)
                received = True
                continue
            if self.appear_then_click(mr_assets.SYNC_TAP, offset=(20, 20), interval=3):
                received = True
                continue

        logger.info(f"Meta sync receive finished, received={received}")
        return received

    def meta_wait_reward_page(self, skip_first_screenshot=True):
        """
        Wait the circle loading animation
        """
        timeout = Timer(2, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("meta_wait_reward_page timeout")
                break
            if self.appear(mr_assets.REWARD_ENTER, offset=(20, 20)):
                logger.info(f"meta_wait_reward_page ends at {mr_assets.REWARD_ENTER}")
                break
            if self.appear(mr_assets.SYNC_ENTER, offset=(20, 20)):
                logger.info(f"meta_wait_reward_page ends at {mr_assets.SYNC_ENTER}")
                break
            if self.appear(mr_assets.SYNC_TAP, offset=(20, 20)):
                logger.info(f"meta_wait_reward_page ends at {mr_assets.SYNC_TAP}")
                break
            if self.meta_sync_notice_appear():
                logger.info("meta_wait_reward_page ends at sync red dot")
                break
            if self.meta_reward_notice_appear():
                logger.info("meta_wait_reward_page ends at reward red dot")
                break

    def run(self):
        self.ui_ensure(page_meta)
        self.meta_wait_reward_page()

        # 同步奖励：sync 指 META 点数累计到 100% 并获得 META 舰船的阶段。
        if self.meta_sync_notice_appear():
            logger.info("Found meta sync red dot or sync tap")
            self.meta_sync_receive()
        else:
            logger.info("No meta sync red dot or sync tap")

        # META 奖励。
        if self.meta_reward_notice_appear():
            logger.info("Found meta reward red dot")
            self.meta_reward_receive()
        else:
            logger.info("No meta reward red dot")


class DossierReward(Combat, UI):
    def meta_reward_notice_appear(self):
        """
        Returns:
            bool: If appear.

        Page:
            in: dossier meta page
        """
        self.device.screenshot()
        if self.appear(mr_assets.DOSSIER_REWARD_RECEIVE, offset=(-40, 10, -10, 40), similarity=0.7):
            logger.info("Found dossier reward red dot")
            return True
        logger.info("No dossier reward red dot")
        return False

    def meta_reward_enter(self, skip_first_screenshot=True):
        """
        Pages:
            in: dossier meta page
            out: DOSSIER_REWARD_CHECK
        """
        logger.info("Dossier reward enter")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DOSSIER_LIST, offset=(20, 20)):
                self.device.click(mr_assets.DOSSIER_REWARD_ENTER)
                continue

            # 结束。
            if self.appear(mr_assets.DOSSIER_REWARD_CHECK, offset=(20, 20)):
                break

    def meta_reward_receive(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Returns:
            bool: If received.

        Pages:
            in: DOSSIER_REWARD_CHECK
            out: DOSSIER_REWARD_CHECK
        """
        logger.hr("Dossier reward receive", level=1)
        confirm_timer = Timer(1, count=3).start()
        received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.match_template_color(mr_assets.DOSSIER_REWARD_RECEIVE, offset=(20, 20), interval=3):
                self.device.click(mr_assets.DOSSIER_REWARD_RECEIVE)
                confirm_timer.reset()
                continue
            if self.handle_popup_confirm("DOSSIER_REWARD"):
                # 锁定新的 META 舰船。
                confirm_timer.reset()
                continue
            if self.handle_get_items():
                received = True
                confirm_timer.reset()
                continue
            if self.handle_get_ship():
                received = True
                confirm_timer.reset()
                continue

            # 结束。
            if not self.appear(mr_assets.DOSSIER_REWARD_RECEIVE, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        logger.info(f"Dossier reward receive finished, received={received}")
        return received

    def run(self):
        from module.os_ash.meta import OpsiAshBeacon

        OpsiAshBeacon(self.config, self.device).ensure_dossier_page()
        if self.meta_reward_notice_appear():
            self.meta_reward_enter()
            self.meta_reward_receive()


class MetaReward(BeaconReward, DossierReward):
    def run(self, category="beacon"):
        if category == "beacon":
            BeaconReward(self.config, self.device).run()
        elif category == "dossier":
            DossierReward(self.config, self.device).run()
        else:
            logger.info(f"Possible wrong parameter {category}, please contact the developers.")
