from typing import TYPE_CHECKING

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.freebies import assets as freebies_assets
from module.logger import logger
from module.ui.page import GOTO_MAIN_WHITE, page_mail, page_main, page_main_white
from module.ui.setting import Setting
from module.ui.ui import UI

if TYPE_CHECKING:
    from module.base.button import Button


class MailSelectSetting(Setting):
    def is_option_active(self, option: Button) -> bool:
        return self.main.image_color_count(option, color=(57, 56, 57), threshold=221, count=50)


class MailWhite(UI):
    @cached_property
    def mail_select_setting(self):
        setting = MailSelectSetting("Mail", main=self)
        setting.reset_first = False
        setting.need_deselect = True
        setting.add_setting(
            setting="contains",
            option_buttons=[
                freebies_assets.MAIL_SELECT_CUBE,
                freebies_assets.MAIL_SELECT_COINS,
                freebies_assets.MAIL_SELECT_OIL,
                freebies_assets.MAIL_SELECT_MERIT,
                freebies_assets.MAIL_SELECT_GEMS,
            ],
            option_names=["cube", "coins", "oil", "merit", "gems"],
            option_default="merit",
        )
        return setting

    @cached_property
    def mail_select_all_setting(self):
        setting = MailSelectSetting("MailAll", main=self)
        setting.reset_first = False
        setting.add_setting(
            setting="all",
            option_buttons=[freebies_assets.MAIL_SELECT_ALL],
            option_names=["all"],
            option_default="all",
        )
        return setting

    def _mail_enter(self, skip_first_screenshot=True):
        """
        Returns:
            int: If having mails

        Page:
            in: page_main_white or MAIL_MANAGE
            out: MAIL_BATCH_CLAIM
        """
        logger.info("Mail enter")
        self.interval_clear([freebies_assets.MAIL_MANAGE])
        timeout = Timer(0.6, count=1)
        has_mail = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束。
            if self.appear(freebies_assets.MAIL_BATCH_CLAIM, offset=(20, 20)):
                logger.info("Mail entered")
                return True
            if self.appear(freebies_assets.MAIL_WHITE_EMPTY, offset=(20, 20)):
                logger.info("Mail empty")
                return False
            if not has_mail and self.appear(GOTO_MAIN_WHITE, offset=(20, 20)):
                timeout.start()
                if timeout.reached():
                    logger.info("Mail empty, wait GOTO_MAIN_WHITE timeout")
                    return False

            # 点击进入。
            if self.appear_then_click(freebies_assets.MAIL_MANAGE, offset=(30, 30), interval=3):
                has_mail = True
                continue
            if self.ui_main_appear_then_click(page_mail, offset=(30, 30), interval=3):
                continue
            if self._handle_mail_reward():
                continue
        return False

    def _mail_quit(self, skip_first_screenshot=True):
        """
        Page:
            in: Any page in page_mail
            out: page_main_white
        """
        logger.info("Mail quit")
        self.interval_clear(
            [
                freebies_assets.MAIL_BATCH_CLAIM,
                GOTO_MAIN_WHITE,
                GET_ITEMS_1,
                GET_ITEMS_2,
            ]
        )
        self.popup_interval_clear()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束。
            if self.ui_page_appear(page_main):
                logger.info("Mail quit to page_main")
                break

            # 点击退出。
            if self.handle_popup_confirm("MAIL_QUIT"):
                continue
            if self.appear(freebies_assets.MAIL_BATCH_CLAIM, offset=(30, 30), interval=3):
                logger.info(f"{freebies_assets.MAIL_BATCH_CLAIM} -> {freebies_assets.MAIL_MANAGE}")
                self.device.click(freebies_assets.MAIL_MANAGE)
                continue
            if self.appear_then_click(GOTO_MAIN_WHITE, offset=(30, 30), interval=3):
                continue
            if self._handle_mail_reward():
                continue

    def _handle_mail_reward(self):
        if self.appear(GET_ITEMS_1, offset=(30, 30), interval=3):
            logger.info(f"{GET_ITEMS_1} -> {freebies_assets.MAIL_BATCH_CLAIM}")
            self.device.click(freebies_assets.MAIL_BATCH_CLAIM)
            return True
        if self.appear(GET_ITEMS_2, offset=(30, 30), interval=3):
            logger.info(f"{GET_ITEMS_2} -> {freebies_assets.MAIL_BATCH_CLAIM}")
            self.device.click(freebies_assets.MAIL_BATCH_CLAIM)
            return True
        return False

    def _mail_claim_execute(self, skip_first_screenshot=True):
        """
        Page:
            in: MAIL_BATCH_CLAIM
            out: page_main_white, may have info_bar

        Returns:
            int: If success to claim
        """
        self.handle_info_bar()
        self.interval_clear(
            [
                freebies_assets.MAIL_BATCH_CLAIM,
                GET_ITEMS_1,
                GET_ITEMS_2,
            ]
        )
        self.popup_interval_clear()

        claimed = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束。
            if claimed and self.appear(freebies_assets.MAIL_BATCH_CLAIM, offset=(30, 30)):
                break
            # 点击领取。
            if not claimed and self.appear_then_click(freebies_assets.MAIL_BATCH_CLAIM, offset=(30, 30), interval=3):
                continue
            if self.handle_popup_confirm("MAIL_CLAIM"):
                claimed = True
                continue
            if self._handle_mail_reward():
                claimed = True
                continue

        success = self.info_bar_count() > 0
        logger.info(f"Mail claim success: {success}")
        return success

    def _mail_delete(self, skip_first_screenshot=True):
        """
        Pages:
            in: MAIL_BATCH_DELETE
            out: MAIL_BATCH_DELETE
        """
        self.handle_info_bar()
        self.interval_clear([freebies_assets.MAIL_BATCH_DELETE])
        self.popup_interval_clear()

        deleted = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束。
            if deleted and self.appear(freebies_assets.MAIL_BATCH_DELETE, offset=(30, 30)):
                break
            # 点击删除。
            if not deleted and self.appear_then_click(freebies_assets.MAIL_BATCH_DELETE, offset=(30, 30), interval=3):
                continue
            if self.handle_popup_confirm("MAIL_CLAIM"):
                deleted = True
                continue
            if self._handle_mail_reward():
                continue

        # 删除成功且没有邮件被删时，会出现 info_bar。
        return True

    def mail_claim(
        self,
        merit=True,
        maintenance=False,
        trade_license=False,
        delete=True,
    ):
        """
        Pages:
            in: page_main_white or MAIL_MANAGE
            out: MAIL_BATCH_CLAIM
        """
        if not self._mail_enter():
            return

        if merit:
            logger.hr("Mail merit", level=2)
            self._mail_enter()
            self.mail_select_setting.set(contains=["merit"])
            self._mail_claim_execute()
        if maintenance:
            logger.hr("Mail maintenance", level=2)
            self._mail_enter()
            self.mail_select_setting.set(contains=["coins", "oil"])
            self._mail_claim_execute()
            self._mail_enter()
            self.mail_select_setting.set(contains=["coins", "oil", "gems"])
            self._mail_claim_execute()
        if trade_license:
            logger.hr("Mail trade license", level=2)
            self._mail_enter()
            self.mail_select_setting.set(contains=["coins", "oil", "cube"])
            self._mail_claim_execute()
        if delete:
            logger.hr("Mail delete", level=2)
            self._mail_enter()
            self.mail_select_all_setting.set(contains=["all"])
            self._mail_delete()

        self._mail_quit()

    def run(self):
        merit = self.config.Mail_ClaimMerit
        maintenance = self.config.Mail_ClaimMaintenance
        trade_license = self.config.Mail_ClaimTradeLicense
        delete = self.config.Mail_DeleteCollected
        logger.info(
            f"Mail reward: merit={merit}, maintenance={maintenance}, trade_license={trade_license}, delete={delete}"
        )
        if not merit and not maintenance and not trade_license:
            logger.warning("Nothing to claim")
            return False

        # 必须使用白色 UI。
        self.ui_ensure(page_main)
        if self.appear(page_main_white.check_button, offset=(30, 30)):
            logger.info("At page_main_white")
        elif self.appear(page_main.check_button, offset=(5, 5)):
            logger.info("At page_main")
        else:
            logger.warning("Unknown page_main, cannot enter mail page")
            return False

        # 领取邮件。
        self.mail_claim(
            merit=merit,
            maintenance=maintenance,
            trade_license=trade_license,
            delete=delete,
        )
        return True
