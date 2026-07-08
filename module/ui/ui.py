from module.base.button import Button
from module.base.decorator import run_once
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP
from module.exception import GameNotRunningError, GamePageUnknownError, RequestHumanTakeover
from module.exercise.assets import EXERCISE_PREPARATION
from module.handler.assets import (
    AUTO_SEARCH_MENU_EXIT,
    BATTLE_PASS_NEW_SEASON,
    BATTLE_PASS_NOTICE,
    GAME_TIPS,
    LOGIN_ANNOUNCE,
    LOGIN_ANNOUNCE_2,
    LOGIN_CHECK,
    LOGIN_RETURN_SIGN,
    MAINTENANCE_ANNOUNCE,
    MONTHLY_PASS_NOTICE,
)
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_CANCEL, WITHDRAW
from module.meowfficer.assets import MEOWFFICER_BUY
from module.ocr.ocr import Ocr
from module.os_handler.assets import AUTO_SEARCH_REWARD, EXCHANGE_CHECK, RESET_FLEET_PREPARATION, RESET_TICKET_POPUP
from module.raid import assets as raid_assets
from module.ui import assets as ui_assets
from module.ui.page import Page, page_campaign, page_event, page_main, page_main_white, page_sp
from module.ui_white import assets as ui_white_assets


class UI(InfoHandler):
    ui_current: Page

    def ui_page_appear(self, page, offset=(30, 30), interval=0):
        """
        判断指定页面是否出现在当前截图中。

        Args:
            page (Page):
            offset:
            interval:
        """
        if page == page_main:
            return self.appear(page_main_white.check_button, offset=offset, interval=interval) or self.appear(
                page_main.check_button, offset=(5, 5), interval=interval
            )
        return self.appear(page.check_button, offset=offset, interval=interval)

    def is_in_main(self, offset=(30, 30), interval=0):
        return self.ui_page_appear(page_main, offset=offset, interval=interval)

    def ui_main_appear_then_click(self, page, offset=(30, 30), interval=3):
        """
        Args:
            page: Destination page
            offset:
            interval:

        Returns:
            bool: If clicked
        """
        if self.appear(page_main.check_button, offset=offset, interval=interval):
            button = page_main.links[page]
            self.device.click(button)
            return True
        if self.appear(page_main_white.check_button, offset=(5, 5), interval=interval):
            button = page_main_white.links[page]
            self.device.click(button)
            return True
        return False

    def ensure_button_execute(self, button, offset=0):
        return bool(
            (isinstance(button, Button) and self.appear(button, offset=offset)) or (callable(button) and button())
        )

    def ui_click(
        self,
        click_button,
        check_button,
        appear_button=None,
        additional=None,
        confirm_wait=1,
        offset=(30, 30),
        retry_wait=10,
        skip_first_screenshot=False,
    ):
        """
        Args:
            click_button (Button):
            check_button (Button, callable):
            appear_button (Button, callable):
            additional (callable):
            confirm_wait (int, float):
            offset (bool, int, tuple):
            retry_wait (int, float):
            skip_first_screenshot (bool):
        """
        logger.hr("UI click")
        if appear_button is None:
            appear_button = click_button

        click_timer = Timer(retry_wait, count=retry_wait // 0.5)
        confirm_wait = confirm_wait if additional is not None else 0
        confirm_timer = Timer(confirm_wait, count=confirm_wait // 0.5).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.ui_process_check_button(check_button, offset=offset):
                confirm_timer.reset()
            elif confirm_timer.reached():
                break

            if click_timer.reached() and (
                (isinstance(appear_button, Button) and self.appear(appear_button, offset=offset))
                or (callable(appear_button) and appear_button())
            ):
                self.device.click(click_button)
                click_timer.reset()
                continue

            if additional is not None and additional():
                continue

    def ui_process_check_button(self, check_button, offset=(30, 30)):
        """
        执行 UI 等待用的检查按钮判断。

        Args:
            check_button (Button, callable, list[Button], tuple[Button]):
            offset:

        Returns:
            bool:
        """
        if isinstance(check_button, Button):
            return self.appear(check_button, offset=offset)
        if callable(check_button):
            return check_button()
        if isinstance(check_button, (list, tuple)):
            return any(self.appear(button, offset=offset) for button in check_button)
        return self.appear(check_button, offset=offset)

    def ui_get_current_page(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot:

        Returns:
            Page:
        """
        logger.info("UI get current page")

        @run_once
        def app_check():
            if not self.device.app_is_running():
                raise GameNotRunningError("Game not running")

        orientation_timer = Timer(5)

        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # End
            if timeout.reached():
                break

            # Known pages
            for page in Page.iter_pages():
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.attr("UI", page.name)
                    self.ui_current = page
                    return page

            # Unknown page but able to handle
            logger.info("Unknown ui page")
            if self.appear_then_click(ui_assets.GOTO_MAIN, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.appear_then_click(ui_white_assets.GOTO_MAIN_WHITE, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.appear_then_click(raid_assets.RPG_HOME, offset=(30, 30), interval=2):
                timeout.reset()
                continue
            if self.ui_additional():
                timeout.reset()
                continue

            app_check()
            # continuously check rotation
            if orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

        # Unknown page, need manual switching
        logger.warning("Unknown ui page")
        logger.attr("EMULATOR__SCREENSHOT_METHOD", self.config.Emulator_ScreenshotMethod)
        logger.attr("EMULATOR__CONTROL_METHOD", self.config.Emulator_ControlMethod)
        logger.attr("SERVER", self.config.SERVER)
        logger.warning("Starting from current page is not supported")
        logger.warning(f"Supported page: {[str(page) for page in Page.iter_pages()]}")
        logger.warning('Supported page: Any page with a "HOME" button on the upper-right')
        logger.critical("Please switch to a supported page before starting Alas")
        raise GamePageUnknownError

    def ui_goto(self, destination, get_ship=True, offset=(30, 30), skip_first_screenshot=True):
        """
        Args:
            destination (Page):
            get_ship:
            offset:
            skip_first_screenshot:
        """
        # Create connection
        Page.init_connection(destination)
        self.interval_clear(list(Page.iter_check_buttons()))

        logger.hr(f"UI goto {destination}")
        while 1:
            ui_assets.GOTO_MAIN.clear_offset()
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Destination page
            if self.ui_page_appear(page=destination, offset=offset):
                logger.info(f"Page arrive: {destination}")
                break

            # Other pages
            clicked = False
            for page in Page.iter_pages():
                if page.parent is None or page.check_button is None:
                    continue
                if self.appear(page.check_button, offset=offset, interval=5):
                    logger.info(f"Page switch: {page} -> {page.parent}")
                    button = page.links[page.parent]
                    self.device.click(button)
                    self.ui_button_interval_reset(button)
                    clicked = True
                    break
            if clicked:
                continue

            # Additional
            if self.ui_additional(get_ship=get_ship):
                continue

        # Reset connection
        Page.clear_connection()

    def ui_ensure(self, destination, skip_first_screenshot=True):
        """
        确保 UI 已切换到目标页面。

        Args:
            destination (Page):
            skip_first_screenshot:

        Returns:
            bool: 是否发生页面切换。
        """
        logger.hr("UI ensure")
        self.ui_get_current_page(skip_first_screenshot=skip_first_screenshot)
        if self.ui_current == destination:
            logger.info(f"Already at {destination}")
            return False
        logger.info(f"Goto {destination}")
        self.ui_goto(destination, skip_first_screenshot=True)
        return True

    def ui_goto_main(self):
        return self.ui_ensure(destination=page_main)

    def ui_goto_campaign(self):
        return self.ui_ensure(destination=page_campaign)

    def ui_goto_event(self):
        return self.ui_ensure(destination=page_event)

    def ui_goto_sp(self):
        return self.ui_ensure(destination=page_sp)

    def ui_ensure_index(
        self,
        index,
        letter,
        next_button,
        prev_button,
        skip_first_screenshot=False,
        fast=True,
        interval=(0.2, 0.3),
    ):
        """
        Args:
            index (int):
            letter (Ocr, callable): OCR button.
            next_button (Button):
            prev_button (Button):
            skip_first_screenshot (bool):
            fast (bool): Default true. False when index is not continuous.
            interval (tuple, int, float): Seconds between two click.
        """
        logger.hr("UI ensure index")
        retry = Timer(1, count=2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            current = letter.ocr(self.device.image) if isinstance(letter, Ocr) else letter(self.device.image)

            logger.attr("Index", current)
            diff = index - current
            if diff == 0:
                break

            if retry.reached():
                button = next_button if diff > 0 else prev_button
                if fast:
                    self.device.multi_click(button, n=abs(diff), interval=interval)
                else:
                    self.device.click(button)
                retry.reset()

    def ui_back(self, check_button, appear_button=None, offset=(30, 30), retry_wait=10, skip_first_screenshot=False):
        return self.ui_click(
            click_button=ui_assets.BACK_ARROW,
            check_button=check_button,
            appear_button=appear_button,
            offset=offset,
            retry_wait=retry_wait,
            skip_first_screenshot=skip_first_screenshot,
        )

    _opsi_reset_fleet_preparation_click = 0

    def _appear_then_click_any(self, button_options):
        return any(self.appear_then_click(button, **kwargs) for button, kwargs in button_options)

    def _return_to_main_from_page(self, page_button):
        if not self.appear(page_button, offset=(30, 30), interval=5):
            return False
        logger.info(f"UI additional: {page_button} -> {ui_assets.GOTO_MAIN}")
        return bool(self.appear_then_click(ui_assets.GOTO_MAIN, offset=(30, 30)))

    def _handle_main_daily_popups(self, get_ship):
        daily_buttons = [
            (LOGIN_ANNOUNCE, {"offset": (30, 30), "interval": 3}),
            (LOGIN_ANNOUNCE_2, {"offset": (30, 30), "interval": 3}),
            (GET_ITEMS_1, {"offset": True, "interval": 3}),
            (GET_ITEMS_2, {"offset": True, "interval": 3}),
        ]
        if self._appear_then_click_any(daily_buttons):
            return True
        if get_ship and self.appear_then_click(GET_SHIP, interval=5):
            return True
        return self.appear_then_click(LOGIN_RETURN_SIGN, offset=(30, 30), interval=3)

    def _handle_main_notice_popups(self):
        notice_buttons = [
            (MONTHLY_PASS_NOTICE, {"offset": (30, 30), "interval": 3}),
            (BATTLE_PASS_NOTICE, {"offset": (30, 30), "interval": 3}),
        ]
        if self._appear_then_click_any(notice_buttons):
            return True
        if self.appear(BATTLE_PASS_NEW_SEASON, offset=(30, 30), interval=3):
            logger.info(f"UI additional: {BATTLE_PASS_NEW_SEASON} -> {ui_assets.BACK_ARROW}")
            self.device.click(ui_assets.BACK_ARROW)
            return True
        return False

    def _handle_main_expired_popups(self):
        if self.handle_popup_single(offset=(-6, 48, 54, 88), name="ITEM_EXPIRED"):
            return True
        return self.handle_popup_single_white()

    def _handle_main_routed_pages(self):
        return self._return_to_main_from_page(ui_assets.SHIPYARD_CHECK) or self._return_to_main_from_page(
            ui_assets.META_CHECK
        )

    def _handle_main_player_page(self):
        if not self.appear(ui_assets.PLAYER_CHECK, offset=(30, 30), interval=3):
            return False
        logger.info(f"UI additional: {ui_assets.PLAYER_CHECK} -> {ui_assets.GOTO_MAIN}")
        return bool(
            self.appear_then_click(ui_assets.GOTO_MAIN, offset=(30, 30))
            or self.appear_then_click(ui_assets.BACK_ARROW, offset=(30, 30))
        )

    def ui_page_main_popups(self, get_ship=True):
        """
        处理 page_main、page_reward 上出现的弹窗。
        """
        # 公会弹窗。
        if self.handle_guild_popup_cancel():
            return True

        return (
            self._handle_main_daily_popups(get_ship=get_ship)
            or self._return_to_main_from_page(ui_assets.EVENT_LIST_CHECK)
            or self._handle_main_notice_popups()
            or self._handle_main_expired_popups()
            or self._handle_main_routed_pages()
            or self._handle_main_player_page()
        )

    def ui_page_os_popups(self):
        """
        Handle popups appear at page_os
        """
        # Opsi reset
        # - Opsi has reset, handle_story_skip() clicks confirm
        # - RESET_TICKET_POPUP
        # - Open exchange shop? handle_popup_confirm() click confirm
        # - EXCHANGE_CHECK, click BACK_ARROW
        if self._opsi_reset_fleet_preparation_click >= 5:
            logger.critical("Failed to confirm OpSi fleets, too many click on RESET_FLEET_PREPARATION")
            logger.critical("Possible reason #1: You haven't set any fleets in operation siren")
            logger.critical(
                "Possible reason #2: Your fleets haven't satisfied the level restrictions in operation siren"
            )
            raise RequestHumanTakeover
        if self.appear_then_click(RESET_TICKET_POPUP, offset=(30, 30), interval=3):
            return True
        if self.appear_then_click(RESET_FLEET_PREPARATION, offset=(30, 30), interval=3):
            self._opsi_reset_fleet_preparation_click += 1
            self.interval_reset(FLEET_PREPARATION)
            self.interval_reset(RESET_TICKET_POPUP)
            return True
        if self.appear(EXCHANGE_CHECK, offset=(30, 30), interval=3):
            logger.info(f"UI additional: {EXCHANGE_CHECK} -> {ui_assets.GOTO_MAIN}")
            ui_assets.GOTO_MAIN.clear_offset()
            self.device.click(ui_assets.GOTO_MAIN)
            return True

        return False

    def _handle_priority_additional_popups(self, get_ship):
        # page_os 的弹窗有 confirm 变体，必须先处理。
        if self.ui_page_os_popups():
            return True
        if self.handle_popup_confirm("UI_ADDITIONAL"):
            return True
        if self.handle_urgent_commission():
            return True
        if self.ui_page_main_popups(get_ship=get_ship):
            return True
        return self.handle_story_skip()

    def _handle_game_tips_popup(self):
        if not self.appear(GAME_TIPS, offset=(30, 30), interval=2):
            return False
        logger.info(f"UI additional: {GAME_TIPS} -> {ui_assets.GOTO_MAIN}")
        self.device.click(ui_assets.GOTO_MAIN)
        return True

    def _handle_dorm_popups(self):
        if self.appear(ui_assets.DORM_INFO, offset=(30, 30), similarity=0.75, interval=3):
            self.device.click(ui_assets.DORM_INFO)
            return True
        return self._appear_then_click_any(
            [
                (ui_assets.DORM_FEED_CANCEL, {"offset": (30, 30), "interval": 3}),
                (ui_assets.DORM_TROPHY_CONFIRM, {"offset": (30, 30), "interval": 3}),
            ]
        )

    def _handle_meowfficer_popups(self):
        if self.appear_then_click(ui_assets.MEOWFFICER_INFO, offset=(30, 30), interval=3):
            self.interval_reset(GET_SHIP)
            return True
        if self.appear(MEOWFFICER_BUY, offset=(30, 30), interval=3):
            logger.info(f"UI additional: {MEOWFFICER_BUY} -> {ui_assets.BACK_ARROW}")
            self.device.click(ui_assets.BACK_ARROW)
            self.interval_reset(GET_SHIP)
            return True
        return False

    def _handle_campaign_preparation_popups(self):
        preparation_buttons = [
            (MAP_PREPARATION, {"offset": (30, 30), "interval": 3}),
            (FLEET_PREPARATION, {"offset": (20, 50), "interval": 3}),
            (raid_assets.RAID_FLEET_PREPARATION, {"offset": (30, 30), "interval": 3}),
        ]
        if any(self.appear(button, **kwargs) for button, kwargs in preparation_buttons):
            self.device.click(MAP_PREPARATION_CANCEL)
            return True
        if self._appear_then_click_any(
            [
                (AUTO_SEARCH_MENU_EXIT, {"offset": (200, 30), "interval": 3}),
                (AUTO_SEARCH_REWARD, {"offset": (50, 50), "interval": 3}),
            ]
        ):
            return True
        return self._handle_withdraw_popup()

    def _handle_withdraw_popup(self):
        if not self.appear(WITHDRAW, offset=(30, 30), interval=3):
            return False
        # 这里故意等待，用来规避 2022-04-07 更新后的客户端卡死问题。
        # 复现方式（基本稳定）：
        # - 进入任意关卡，例如 12-4。
        # - 停止并重启游戏。
        # - 运行 Alas 的 `Main` 任务。
        # - Alas 切换到 page_campaign，并从已进入的关卡撤退。
        # - 客户端卡在 page_campaign W12，点击屏幕任意位置都没有响应。
        # - 再次重启客户端即可恢复。
        logger.info("WITHDRAW button found, wait until map loaded to prevent bugs in game client")
        self.device.sleep(2)
        self.device.screenshot()
        if self.appear_then_click(WITHDRAW, offset=(30, 30)):
            self.interval_reset(WITHDRAW)
            return True
        logger.warning("WITHDRAW button does not exist anymore")
        self.interval_reset(WITHDRAW)
        return False

    def _handle_login_popups(self):
        return self._appear_then_click_any(
            [
                (LOGIN_CHECK, {"offset": (30, 30), "interval": 3}),
                (MAINTENANCE_ANNOUNCE, {"offset": (30, 30), "interval": 3}),
            ]
        )

    def _handle_exercise_preparation_popup(self):
        if not self.appear(EXERCISE_PREPARATION, interval=3):
            return False
        logger.info(f"UI additional: {EXERCISE_PREPARATION} -> {ui_assets.GOTO_MAIN}")
        self.device.click(ui_assets.GOTO_MAIN)
        return True

    def _handle_white_main_tab_switch(self):
        if not self.appear(ui_white_assets.MAIN_GOTO_MEMORIES_WHITE, interval=3):
            return False
        logger.info(
            f"UI additional: {ui_white_assets.MAIN_GOTO_MEMORIES_WHITE} -> {ui_white_assets.MAIN_TAB_SWITCH_WHITE}"
        )
        self.device.click(ui_white_assets.MAIN_TAB_SWITCH_WHITE)
        return True

    def ui_additional(self, get_ship=True):
        """
        处理 UI 切换期间可能出现的干扰弹窗。

        Args:
            get_ship:
        """
        return (
            self._handle_priority_additional_popups(get_ship=get_ship)
            or self._handle_game_tips_popup()
            or self._handle_dorm_popups()
            or self._handle_meowfficer_popups()
            or self._handle_campaign_preparation_popups()
            or self._handle_login_popups()
            or self._handle_exercise_preparation_popup()
            or self.handle_idle_page()
            or self._handle_white_main_tab_switch()
        )

    def handle_idle_page(self):
        """
        Returns:
            bool: If handled
        """
        timer = self.get_interval_timer(ui_assets.IDLE, interval=3)
        if not timer.reached():
            return False
        if ui_assets.IDLE.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f"UI additional: {ui_assets.IDLE} -> {ui_assets.REWARD_GOTO_MAIN}")
            self.device.click(ui_assets.REWARD_GOTO_MAIN)
            timer.reset()
            return True
        if ui_assets.IDLE_2.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f"UI additional: {ui_assets.IDLE_2} -> {ui_assets.REWARD_GOTO_MAIN}")
            self.device.click(ui_assets.REWARD_GOTO_MAIN)
            timer.reset()
            return True
        if ui_assets.IDLE_3.match_luma(self.device.image, offset=(5, 5)):
            logger.info(f"UI additional: {ui_assets.IDLE_3} -> {ui_assets.REWARD_GOTO_MAIN}")
            self.device.click(ui_assets.REWARD_GOTO_MAIN)
            timer.reset()
            return True
        return False

    def _iter_button_interval_reset_targets(self, button):
        if button in (
            ui_assets.MEOWFFICER_GOTO_DORMMENU,
            ui_assets.DORMMENU_GOTO_DORM,
            ui_assets.DORMMENU_GOTO_MEOWFFICER,
        ):
            yield GET_SHIP
        for switch_button in page_main.links.values():
            if button == switch_button:
                yield GET_SHIP
        if button in [ui_assets.MAIN_GOTO_REWARD, ui_white_assets.MAIN_GOTO_REWARD_WHITE]:
            yield GET_SHIP
        if button == ui_assets.REWARD_GOTO_TACTICAL:
            yield ui_white_assets.REWARD_GOTO_TACTICAL_WHITE
        if button == ui_white_assets.REWARD_GOTO_TACTICAL_WHITE:
            yield ui_assets.REWARD_GOTO_TACTICAL
        if button in [ui_assets.MAIN_GOTO_CAMPAIGN, ui_white_assets.MAIN_GOTO_CAMPAIGN_WHITE]:
            yield GET_SHIP
            # 信浓活动和 raid 的标题相同。
            yield ui_assets.RAID_CHECK
        if button == ui_assets.SHOP_GOTO_SUPPLY_PACK:
            yield EXCHANGE_CHECK

    def ui_button_interval_reset(self, button):
        """
        重置部分按钮的点击间隔，避免误触。

        Args:
            button (Button):
        """
        for reset_button in self._iter_button_interval_reset_targets(button):
            self.interval_reset(reset_button)
        if button in [raid_assets.RPG_GOTO_STAGE, raid_assets.RPG_GOTO_STORY, raid_assets.RPG_LEAVE_CITY]:
            self.interval_timer[GET_SHIP.name] = Timer(5).reset()
