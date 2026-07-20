from typing import TYPE_CHECKING, Literal, Never

from module.base.button import Button, ButtonGrid
from module.base.timer import Timer
from module.base.utils import color_similar, get_color, resize
from module.combat.assets import GET_ITEMS_1
from module.exception import HumanTakeoverRequiredError, ScriptError
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON
from module.logger import logger
from module.retire import assets as retire_assets
from module.retire.enhancement import Enhancement
from module.retire.scanner import Ship, ShipScanner
from module.retire.setting import QuickRetireSettingHandler
from module.ui.scroll import Scroll

if TYPE_CHECKING:
    from collections.abc import Collection

type RetireRarity = Literal["N", "R", "SR", "SSR"]
type RetireMode = Literal["one_click_retire", "old_retire"]

CARD_GRIDS = ButtonGrid(
    origin=(93, 76), delta=(164 + 2 / 3, 227), button_shape=(138, 204), grid_shape=(7, 2), name="CARD"
)
CARD_RARITY_GRIDS = ButtonGrid(
    origin=(93, 76), delta=(164 + 2 / 3, 227), button_shape=(138, 5), grid_shape=(7, 2), name="RARITY"
)

CARD_RARITY_COLORS: dict[RetireRarity, tuple[int, int, int]] = {
    "N": (174, 176, 187),
    "R": (106, 195, 248),
    "SR": (151, 134, 254),
    "SSR": (248, 223, 107),
    # 不支持婚舰卡片。
}

RETIRE_CONFIRM_SCROLL = Scroll(
    retire_assets.RETIRE_CONFIRM_SCROLL_AREA, color=(74, 77, 110), name="STRATEGIC_SEARCH_SCROLL"
)
RETIRE_CONFIRM_SCROLL.color_threshold = 240  # 背景色是 (66, 72, 77)，默认阈值 (256-221)=35 不够区分。
UNKNOWN_RETIRE_MODE_TEMPLATE = "Unknown retire mode: {mode}"


class Retirement(Enhancement, QuickRetireSettingHandler):
    _unable_to_enhance = False
    _have_kept_cv = True

    map_cat_attack_timer = Timer(2)

    @property
    def retire_keep_common_cv(self) -> bool:
        return self.config.is_task_enabled("GemsFarming")

    def _retirement_choose(
        self,
        amount: int = 10,
        target_rarity: Collection[RetireRarity] = ("N",),
    ) -> int:
        """选择 0 至 10 张指定稀有度舰船，并返回实际选择数。"""
        cards = []
        rarity: list[RetireRarity] = []
        for x, y, button in CARD_RARITY_GRIDS.generate():
            card_color = get_color(image=self.device.image, area=button.area)
            f = False
            for r, rarity_color in CARD_RARITY_COLORS.items():
                if color_similar(card_color, rarity_color, threshold=15):
                    cards.append([x, y])
                    rarity.append(r)
                    f = True

            if not f:
                logger.warning(f"Unknown rarity color. Grid: ({x}, {y}). Color: {card_color}")

        logger.info(" ".join([r.rjust(3) for r in rarity[:7]]))
        logger.info(" ".join([r.rjust(3) for r in rarity[7:]]))

        selected = 0
        for card, r in zip(cards, rarity, strict=False):
            if r in target_rarity:
                self.device.click(CARD_GRIDS[card])
                self.device.sleep((0.1, 0.15))
                selected += 1
            if selected >= amount:
                break
        return selected

    def _clear_retirement_confirm_intervals(self) -> None:
        for button in [
            retire_assets.SHIP_CONFIRM,
            retire_assets.SHIP_CONFIRM_2,
            retire_assets.EQUIP_CONFIRM,
            retire_assets.EQUIP_CONFIRM_2,
            GET_ITEMS_1,
            retire_assets.SR_SSR_CONFIRM,
        ]:
            self.interval_clear(button)
        self.popup_interval_clear()

    def _retirement_confirm_finished(self, timeout: Timer, *, executed: bool) -> bool:
        if timeout.reached():
            # GemsFarming 占用中的舰船没有装备可分解，executed 不会变成 True。
            # 这里先用超时兜底，后续可以从状态源头继续收窄。
            logger.warning("Wait _retirement_confirm timeout, assume finished")
            return True
        # 有时装备确认弹窗没有黑色模糊背景，会和退役检查点同时出现。
        if self.appear(retire_assets.IN_RETIREMENT_CHECK, offset=(20, 20)) and not self.appear(
            retire_assets.EQUIP_CONFIRM, offset=(30, 30)
        ):
            return executed

        timeout.reset()
        return False

    def _reset_retirement_confirm_button_intervals(self) -> None:
        # 避免再次点到底层确认按钮。
        self.interval_reset([retire_assets.SHIP_CONFIRM, retire_assets.SHIP_CONFIRM_2])
        # EQUIP_CONFIRM_2 可能会被识别成弹窗确认。
        self.interval_reset([retire_assets.EQUIP_CONFIRM, retire_assets.EQUIP_CONFIRM_2])

    def _handle_retirement_sr_ssr_confirm(self) -> bool:
        if not (
            self._unable_to_enhance
            or self.config.OldRetire_SR
            or self.config.OldRetire_SSR
            or self.config.Retirement_RetireMode == "one_click_retire"
        ):
            return False

        if self.handle_popup_confirm(name="RETIRE_SR_SSR", offset=(20, 50)):
            self._reset_retirement_confirm_button_intervals()
            return True
        if self.appear_then_click(retire_assets.SR_SSR_CONFIRM, offset=(20, 50), interval=2):
            self._reset_retirement_confirm_button_intervals()
            return True
        return False

    def _handle_ship_retirement_confirm(self) -> bool:
        if self.match_template_color(retire_assets.SHIP_CONFIRM_2, offset=(30, 30), interval=2):
            if self.retire_keep_common_cv and not self._have_kept_cv:
                self.keep_one_common_cv()
            self.device.click(retire_assets.SHIP_CONFIRM_2)
            # 即将出现获取物品弹窗，避免重新进入舰船确认。
            self.interval_clear(GET_ITEMS_1)
            self.interval_reset([retire_assets.SHIP_CONFIRM, retire_assets.SHIP_CONFIRM_2])
            return True
        if self.match_template_color(retire_assets.SHIP_CONFIRM, offset=(30, 30), interval=2):
            self.device.click(retire_assets.SHIP_CONFIRM)
            return True
        return False

    def _handle_equipment_retirement_confirm(self, *, executed: bool) -> tuple[bool, bool]:
        if self.appear_then_click(retire_assets.EQUIP_CONFIRM, offset=(30, 30), interval=2):
            return True, executed
        if self.appear_then_click(retire_assets.EQUIP_CONFIRM_2, offset=(30, 30), interval=2):
            self.interval_clear(GET_ITEMS_1)
            return True, True
        return False, executed

    def _handle_retirement_get_items(self) -> bool:
        if not self.appear(GET_ITEMS_1, offset=(30, 30), interval=2):
            return False

        self.device.click(retire_assets.GET_ITEMS_1_RETIREMENT_SAVE)
        self.interval_reset(retire_assets.SHIP_CONFIRM)
        # 接下来会出现装备确认。
        self.interval_clear([retire_assets.EQUIP_CONFIRM, retire_assets.EQUIP_CONFIRM_2])
        return True

    def _retirement_confirm(self, *, skip_first_screenshot: bool = True) -> None:
        """从一键或旧版退役确认弹窗完成退役，结束于退役检查页。"""
        logger.info("Retirement confirm")
        executed = False
        self._clear_retirement_confirm_intervals()
        timeout = Timer(10, count=10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._retirement_confirm_finished(timeout, executed=executed):
                break
            if self._handle_retirement_sr_ssr_confirm():
                continue
            if self._handle_ship_retirement_confirm():
                continue
            handled, executed = self._handle_equipment_retirement_confirm(executed=executed)
            if handled:
                continue
            if self._handle_retirement_get_items():
                continue

    def retirement_appear(self) -> bool:
        return (
            self.appear(retire_assets.RETIRE_APPEAR_1, offset=30)
            and self.appear(retire_assets.RETIRE_APPEAR_2, offset=30)
            and self.appear(retire_assets.RETIRE_APPEAR_3, offset=30)
        )

    def _retirement_quit(self) -> None:
        def check_func() -> bool:
            return not self.appear(retire_assets.IN_RETIREMENT_CHECK, offset=(20, 20)) and not self.appear(
                retire_assets.DOCK_CHECK, offset=(20, 20)
            )

        self.ui_back(check_button=check_func, skip_first_screenshot=True)

    @property
    def _retire_rarity(self) -> set[RetireRarity]:
        rarity: set[RetireRarity] = set()
        if self.config.OldRetire_N:
            rarity.add("N")
        if self.config.OldRetire_R:
            rarity.add("R")
        if self.config.OldRetire_SR:
            rarity.add("SR")
        if self.config.OldRetire_SSR:
            rarity.add("SSR")
        return rarity

    def _retire_wait_slow_retire(self, *, skip_first_screenshot: bool = True) -> bool:
        """等待慢设备或大船坞延迟出现的确认弹窗；60 秒超时会抛出 GameStuckError。"""
        logger.info("Wait slow retire")
        self.device.click_record_clear()
        self.device.stuck_record_clear()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(retire_assets.SHIP_CONFIRM_2, offset=(30, 30)):
                return True
        return False

    def _wait_one_click_retire_confirm(self, *, skip_first_screenshot: bool = True) -> tuple[bool, int]:
        click_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(retire_assets.SHIP_CONFIRM_2, offset=(30, 30)):
                return True, 0
            if self.info_bar_count():
                logger.info("No more ships to retire.")
                return False, 0

            if click_count >= 5:
                logger.warning("Failed to select ships using ONE_CLICK_RETIREMENT after 5 trial")
                if self._retire_wait_slow_retire():
                    # 等到了，继续在同一张截图上触发一键退役判断。
                    pass
                else:
                    # 可能是游戏状态异常；标记本轮完成，让上层重新进入。
                    return False, 10
            if self.appear_then_click(retire_assets.ONE_CLICK_RETIREMENT, offset=(20, 20), interval=2):
                click_count += 1
                continue
        return False, 0

    def retire_ships_one_click(self) -> int:
        logger.hr("Retirement")
        logger.info("Using one click retirement.")
        # 一键退役无需等待船坞检查完成。
        self.dock_favourite_set(wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        total = 0

        if self.retire_keep_common_cv:
            self._have_kept_cv = False

        self.handle_info_bar()
        has_confirm, assumed_total = self._wait_one_click_retire_confirm()
        total += assumed_total
        if has_confirm:
            self._retirement_confirm()
            total += 10

        logger.info(f"Total retired round: {total // 10}")
        return total

    def retire_ships_old(
        self,
        amount: int | None = None,
        rarity: Collection[RetireRarity] | None = None,
    ) -> int:
        """按指定稀有度退役 amount 艘舰船并返回实际总数；amount=None 时使用配置值。"""
        if amount is None:
            amount = self._retire_amount
        if rarity is None:
            rarity = self._retire_rarity
        logger.hr("Retirement")
        logger.info(f"Amount={amount}. Rarity={rarity}")

        correspond_name = {"N": "common", "R": "rare", "SR": "elite", "SSR": "super_rare"}
        rarity_filters = [correspond_name[i] for i in rarity]
        self.dock_sort_method_dsc_set(enable=False, wait_loading=False)
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_filter_set(sort="level", index="all", faction="all", rarity=rarity_filters, extra="no_limit")

        total = 0

        if self.retire_keep_common_cv:
            self._have_kept_cv = False

        while amount:
            selected = self._retirement_choose(amount=min(amount, 10), target_rarity=rarity)
            total += selected
            if selected == 0:
                break
            self.device.screenshot()
            if not self.match_template_color(retire_assets.SHIP_CONFIRM, offset=(30, 30)):
                logger.warning("No ship selected, retrying")
                continue

            self._retirement_confirm()

            amount -= selected
            if amount <= 0:
                break

            self.handle_dock_cards_loading()
            continue

        self.dock_sort_method_dsc_set(enable=True, wait_loading=False)
        self.dock_filter_set()
        logger.info(f"Total retired: {total}")
        return total

    @staticmethod
    def _gems_farming_retire_candidates(ships: list[Ship], *, keep_one: bool) -> list[Ship]:
        candidates = list(ships)
        if not keep_one:
            return candidates
        if len(candidates) < 2:
            return []
        # 尽量保留等级最低的一艘。
        candidates.sort(key=lambda ship: -(ship.level or 0))
        return candidates[:-1]

    def retire_gems_farming_flagships(self, *, keep_one: bool = True) -> int:
        """退役 GemsFarming 遗留的普通航母：等级大于 1、未编队且空闲。"""
        logger.info("Retire abandoned flagships of GemsFarming")

        gems_farming_enable: bool = self.config.is_task_enabled("GemsFarming")
        if not gems_farming_enable:
            logger.info("Not in GemsFarming, skip")
            return 0

        self.dock_favourite_set(wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        self.dock_filter_set(index="cv", rarity="common", extra="not_level_max", sort="level")

        scanner = ShipScanner(rarity="common", fleet=0, status="free", level=(2, 100))
        scanner.disable("emotion")

        total = 0
        _ = self._have_kept_cv
        self._have_kept_cv = True

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self.handle_info_bar()
            scanned_ships = scanner.scan(self.device.image)
            if not scanned_ships:
                break
            ships = self._gems_farming_retire_candidates(scanned_ships, keep_one=keep_one)
            if not ships:
                break

            for ship in ships:
                self.device.click(ship.button)
                self.device.sleep((0.1, 0.15))
                total += 1

            self._retirement_confirm()

            # 不足十艘说明本页已经扫完，可以直接退出。
            if len(ships) < 10:
                break

        self._have_kept_cv = _
        # 退役已完成且即将退出，无需等待筛选加载。
        self.dock_filter_set(wait_loading=False)

        return total

    def _reset_retirement_popup_timers(self) -> None:
        self.interval_reset([AUTO_SEARCH_MAP_OPTION_OFF, AUTO_SEARCH_MAP_OPTION_ON])
        self.map_cat_attack_timer.reset()

    def _enter_retirement_popup(self, appear_button: Button, check_button: Button) -> bool:
        if not self.appear_then_click(appear_button, offset=(20, 20), interval=3):
            return False

        self.interval_clear(check_button)
        self._reset_retirement_popup_timers()
        return True

    def _finish_retirement_popup(self, check_button: Button) -> None:
        self.interval_reset(check_button)
        self.map_cat_attack_timer.reset()

    def _handle_unable_to_enhance_retirement(self) -> bool:
        if self._enter_retirement_popup(retire_assets.RETIRE_APPEAR_1, retire_assets.IN_RETIREMENT_CHECK):
            return False
        if not self.appear(retire_assets.IN_RETIREMENT_CHECK, offset=(20, 20), interval=10):
            return False

        self._retire_handler(mode="one_click_retire")
        self._unable_to_enhance = False
        self._finish_retirement_popup(retire_assets.IN_RETIREMENT_CHECK)
        return True

    def _update_enhance_retirement_state(self, total: int, remain: int) -> None:
        if not total:
            logger.info("No ship to enhance, but dock full, will try retire")
            self._unable_to_enhance = True
        logger.info(f"The remaining spare dock amount is {remain}")
        if remain < 3:
            logger.info("Too few spare docks, retire next time")
            self._unable_to_enhance = True

    def _handle_enhance_retirement(self) -> bool:
        if self._enter_retirement_popup(retire_assets.RETIRE_APPEAR_3, retire_assets.DOCK_CHECK):
            return False
        if not self.appear(retire_assets.DOCK_CHECK, offset=(20, 20), interval=10):
            return False

        self.handle_dock_cards_loading()
        total, remain = self._enhance_handler()
        self._update_enhance_retirement_state(total, remain)
        self._finish_retirement_popup(retire_assets.DOCK_CHECK)
        return True

    def _handle_direct_retirement(self) -> bool:
        if self._enter_retirement_popup(retire_assets.RETIRE_APPEAR_1, retire_assets.IN_RETIREMENT_CHECK):
            return False
        if not self.appear(retire_assets.IN_RETIREMENT_CHECK, offset=(20, 20), interval=10):
            return False

        self._retire_handler()
        self._unable_to_enhance = False
        self._finish_retirement_popup(retire_assets.IN_RETIREMENT_CHECK)
        return True

    def handle_retirement(self) -> bool:
        # 2025.05.29 进入船坞时会弹出换装提示。
        if self.handle_game_tips():
            return True
        if self._unable_to_enhance:
            return self._handle_unable_to_enhance_retirement()
        if self.config.Retirement_RetireMode == "enhance":
            return self._handle_enhance_retirement()
        return self._handle_direct_retirement()

    @staticmethod
    def _raise_no_ship_retired(message: str) -> Never:
        logger.critical("No ship retired")
        logger.critical(message)
        raise HumanTakeoverRequiredError

    def _retry_one_click_retire_after_filter_reset(self, total: int) -> int:
        if total:
            return total

        logger.warning("No ship retired, trying to reset dock filter and disable favourite, then retire again")
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_filter_set()
        return self.retire_ships_one_click()

    def _retry_one_click_retire_settings(self, total: int) -> int:
        if not self.server_support_quick_retire_setting_fallback():
            return total

        # 用户可能已经把 filter_5 设成 all，所以先保留当前第 5 项。
        if not total:
            logger.warning("No ship retired, trying to reset the first 4 quick retire settings")
            self.quick_retire_setting_set(filter_5=None)
            total = self.retire_ships_one_click()
        if not total:
            logger.warning('No ship retired, trying to reset quick retire settings to "keep_limit_break"')
            self.quick_retire_setting_set(filter_5="keep_limit_break")
            total = self.retire_ships_one_click()
        if not total and self.config.OneClickRetire_KeepLimitBreak == "do_not_keep":
            logger.warning('No ship retired, trying to reset quick retire settings to "all"')
            self.quick_retire_setting_set(filter_5="all")
            total = self.retire_ships_one_click()
        return total

    def _retire_one_click_with_fallbacks(self) -> int:
        total = self.retire_ships_one_click()
        total = self._retry_one_click_retire_after_filter_reset(total)
        total = self._retry_one_click_retire_settings(total)
        total += self.retire_gems_farming_flagships(keep_one=total > 0)
        if not total:
            self._raise_no_ship_retired(
                'Please configure your "Quick Retire Options" in game, make sure it can select ships to retire'
            )
        return total

    def _retire_old_with_flagships(self) -> int:
        self.handle_dock_cards_loading()
        total = self.retire_ships_old()
        total += self.retire_gems_farming_flagships()
        if not total:
            self._raise_no_ship_retired(
                "Please configure your retirement settings in Alas, make sure it can select ships to retire"
            )
        return total

    def _retire_handler(self, mode: RetireMode | None = None) -> int:
        """以 one_click_retire 或 old_retire 模式退役，返回数量并恢复到弹窗前页面。"""
        if mode is None:
            configured_mode = self.config.Retirement_RetireMode
            if configured_mode == "one_click_retire":
                mode = "one_click_retire"
            elif configured_mode == "old_retire":
                mode = "old_retire"
            else:
                message = UNKNOWN_RETIRE_MODE_TEMPLATE.format(mode=configured_mode)
                raise ScriptError(message)

        if mode == "one_click_retire":
            total = self._retire_one_click_with_fallbacks()
        elif mode == "old_retire":
            total = self._retire_old_with_flagships()
        else:
            message = UNKNOWN_RETIRE_MODE_TEMPLATE.format(mode=mode)
            raise ScriptError(message)

        self._retirement_quit()
        self.config.DOCK_FULL_TRIGGERED = True

        return total

    def _retire_select_one(self, button: Button, *, skip_first_screenshot: bool = True) -> bool:
        count = 0
        retire_assets.RETIRE_COIN.load_color(self.device.image)
        retire_assets.RETIRE_COIN.mark_match_initialized()
        self.interval_clear(retire_assets.SHIP_CONFIRM_2)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 退役硬币消失，表示选择完成。
            if not retire_assets.RETIRE_COIN.match(self.device.image, offset=(20, 20), similarity=0.97):
                return True
            if count > 3:
                logger.warning("_retire_select_one failed after 3 trial")
                return False

            if self.appear(retire_assets.SHIP_CONFIRM_2, offset=(30, 30), interval=2):
                self.device.click(button)
                count += 1
                continue
        return False

    def retirement_get_common_rarity_cv_in_page(self) -> Button | None:
        if self.config.GemsFarming_CommonCV == "any":
            for common_cv_name in ["BOGUE", "HERMES", "LANGLEY", "RANGER"]:
                template = getattr(retire_assets, f"TEMPLATE_{common_cv_name}")
                sim, button = template.match_result(resize(self.device.image, size=(1189, 669)))

                if sim > self.config.COMMON_CV_THRESHOLD:
                    return Button(
                        button=tuple(_ * 155 // 144 for _ in button.button),
                        area=button.area,
                        color=button.color,
                        name=f"TEMPLATE_{common_cv_name}_RETIRE",
                    )

            return None
        template = getattr(retire_assets, f"TEMPLATE_{self.config.GemsFarming_CommonCV.upper()}")
        sim, button = template.match_result(resize(self.device.image, size=(1189, 669)))

        if sim > self.config.COMMON_CV_THRESHOLD:
            return Button(
                button=tuple(_ * 155 // 144 for _ in button.button),
                area=button.area,
                color=button.color,
                name=f"TEMPLATE_{self.config.GemsFarming_CommonCV.upper()}_RETIRE",
            )

        return None

    def retirement_get_common_rarity_cv(self, *, skip_first_screenshot: bool = False) -> Button | None:
        swipe_count = 0
        disappear_confirm = Timer(2, count=6)
        top_checked = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            button = self.retirement_get_common_rarity_cv_in_page()
            if button is not None:
                return button

            if RETIRE_CONFIRM_SCROLL.appear(main=self):
                disappear_confirm.clear()
            else:
                disappear_confirm.start()
                if disappear_confirm.reached():
                    logger.warning("Scroll bar disappeared, stop")
                    break
                continue

            if not top_checked:
                top_checked = True
                logger.info("Find common CV from bottom to top")
                RETIRE_CONFIRM_SCROLL.set_bottom(main=self)
                continue
            if RETIRE_CONFIRM_SCROLL.at_top(main=self):
                logger.info("Scroll bar reached top, stop")
                break
            if swipe_count >= 7:
                logger.info("Reached maximum swipes to find common CV")
                break
            RETIRE_CONFIRM_SCROLL.prev_page(main=self)
            swipe_count += 1

        return button

    def keep_one_common_cv(self) -> None:
        logger.info("Keep one common CV")
        button = self.retirement_get_common_rarity_cv()
        if button is not None:
            self._retire_select_one(button)
            self._have_kept_cv = True
        logger.info("Keep one common CV end")
