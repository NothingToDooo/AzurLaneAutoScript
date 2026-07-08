from dataclasses import dataclass

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.config.utils import get_os_reset_remain
from module.exception import ScriptError
from module.logger import logger
from module.os_shop.akashi_shop import AkashiShop
from module.os_shop.assets import PORT_SUPPLY_CHECK, SHOP_BUY_CONFIRM
from module.os_shop.port_shop import PortShop
from module.os_shop.ui import OS_SHOP_SCROLL
from module.shop.assets import AMOUNT_MAX, AMOUNT_MINUS, AMOUNT_PLUS, SHOP_BUY_CONFIRM_AMOUNT, SHOP_CLICK_SAFE_AREA
from module.shop.assets import SHOP_BUY_CONFIRM as OS_SHOP_BUY_CONFIRM
from module.shop.clerk import OCR_SHOP_AMOUNT
from module.ui.ui import UiIndexControls


@dataclass(slots=True)
class _OSShopBuyState:
    button: object
    amount_finish: bool = False
    success: bool = False
    set_amount_retry: int = 0


class OSShop(PortShop, AkashiShop):
    def os_shop_buy_execute(self, button, skip_first_screenshot=True) -> bool:
        """
        Args:
            button: Item to buy
            skip_first_screenshot:

        Pages:
            in: PORT_SUPPLY_CHECK
        """
        state = _OSShopBuyState(button=button)
        self.interval_clear(
            [
                PORT_SUPPLY_CHECK,
                SHOP_BUY_CONFIRM_AMOUNT,
                SHOP_BUY_CONFIRM,
                OS_SHOP_BUY_CONFIRM,
                GET_ITEMS_1,
                SHOP_CLICK_SAFE_AREA,
            ]
        )

        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._handle_os_shop_buy_rewards(state):
                continue
            if self._handle_os_shop_buy_confirm_buttons():
                continue
            amount_handled, amount_failed = self._handle_os_shop_buy_amount(
                state, skip_first_screenshot=skip_first_screenshot
            )
            if amount_failed:
                break
            if amount_handled:
                continue
            if self._handle_os_shop_buy_amount_confirm(state):
                continue
            if self._handle_os_shop_buy_misc(state):
                continue
            if self._os_shop_buy_finished(state):
                break

        return state.success

    def _handle_os_shop_buy_rewards(self, state: _OSShopBuyState) -> bool:
        if not self.handle_map_get_items(interval=3):
            return False

        self.interval_clear(PORT_SUPPLY_CHECK)
        state.success = True
        return True

    def _handle_os_shop_buy_confirm_buttons(self) -> bool:
        for button in (SHOP_BUY_CONFIRM, OS_SHOP_BUY_CONFIRM):
            if self.appear_then_click(button, offset=(20, 20), interval=3):
                self.interval_reset(button)
                return True
        return False

    def _handle_os_shop_buy_amount(self, state: _OSShopBuyState, *, skip_first_screenshot: bool) -> tuple[bool, bool]:
        if state.amount_finish:
            return False, False
        if not self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20)):
            return False, False

        state.amount_finish = self.shop_buy_amount_handler(state.button)
        state.set_amount_retry += 1
        if not state.amount_finish and state.set_amount_retry > 3:
            logger.warning(f"Item {state.button.name} cant get amount.")
            self.close_shop_buy_confirm_amount(skip_first_screenshot)
            return True, True
        return True, False

    def _handle_os_shop_buy_amount_confirm(self, state: _OSShopBuyState) -> bool:
        if not state.amount_finish:
            return False
        if not self.appear_then_click(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
            return False

        self.interval_reset(SHOP_BUY_CONFIRM_AMOUNT)
        return True

    def _handle_os_shop_buy_misc(self, state: _OSShopBuyState) -> bool:
        if self.handle_popup_confirm("SHOP_BUY"):
            return True
        return self._handle_os_shop_buy_entry(state)

    def _handle_os_shop_buy_entry(self, state: _OSShopBuyState) -> bool:
        if state.success:
            return False
        if not self.appear(PORT_SUPPLY_CHECK, offset=(20, 20), interval=5):
            return False

        state.amount_finish = False
        self.device.click(state.button)
        return True

    def _os_shop_buy_finished(self, state: _OSShopBuyState) -> bool:
        return state.success and self.appear(PORT_SUPPLY_CHECK, offset=(20, 20))

    def os_shop_buy(self, select_func) -> int:
        """
        Args:
            select_func:
                Function to select items to buy.

            in: PORT_SUPPLY_CHECK
        """
        count = 0
        for _ in range(12):
            button = select_func()
            if button is None:
                logger.info("Shop buy finished")
                return count
            self.os_shop_buy_execute(button)
            count += 1
            continue

        logger.warning("Too many items to buy, stopped")
        return count

    def close_shop_buy_confirm_amount(self, skip_first_screenshot=True):
        """
        Close shop buy confirm amount.

        Args:
            skip_first_screenshot:

        Pages:
            in: SHOP_BUY_CONFIRM_AMOUNT
        """
        self.interval_clear([PORT_SUPPLY_CHECK, SHOP_BUY_CONFIRM_AMOUNT])
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
                self.interval_clear(SHOP_BUY_CONFIRM_AMOUNT)
                break

            if self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
                self.device.click(SHOP_CLICK_SAFE_AREA)

    def shop_buy_amount_handler(self, item, skip_first_screenshot=True):
        """处理商店购买数量。

        Args:
            item

        Raises:
            ScriptError: OCR_SHOP_AMOUNT
        """
        limit = self._shop_buy_amount_read_limit(skip_first_screenshot=skip_first_screenshot)
        if limit == 0:
            return False

        count = self._shop_buy_amount_available_count(item)
        if count == 1:
            return True

        total_count = self._shop_buy_amount_total_count(item)
        limit, set_to_max = self._shop_buy_amount_target(count=count, total_count=total_count)

        self.interval_clear(AMOUNT_MAX)
        if set_to_max:
            self._shop_buy_amount_set_to_max()

        self.ui_ensure_index(
            limit,
            UiIndexControls(letter=OCR_SHOP_AMOUNT, prev_button=AMOUNT_MINUS, next_button=AMOUNT_PLUS),
            skip_first_screenshot=True,
        )
        return True

    def _shop_buy_amount_read_limit(self, skip_first_screenshot=True) -> int:
        retry = Timer(0, count=3)
        retry.start()
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            limit = OCR_SHOP_AMOUNT.ocr(self.device.image)

            if limit == 0:
                logger.warning("OCR_SHOP_AMOUNT resulted 0, retrying")
                self.close_shop_buy_confirm_amount()
                return 0

            if limit > 0:
                return limit

            if retry.reached():
                logger.critical("OCR_SHOP_AMOUNT resulted error; asset may be compromised")
                raise ScriptError

    def _shop_buy_amount_available_count(self, item) -> int:
        currency = self.get_currency_coins(item)
        return min(int(currency // item.price), item.count)

    def _shop_buy_amount_total_count(self, item) -> int:
        coins = self.get_coins_no_limit(item)
        return min(int(coins // item.price), item.count)

    @staticmethod
    def _shop_buy_amount_target(*, count: int, total_count: int) -> tuple[int, bool]:
        set_to_max = False
        # Avg count of all items(no PurpleCoins) is 8.9, so use 10.
        if count <= 10:
            if count - 1 > total_count - count:
                set_to_max = True
            limit = count
        elif total_count - count <= 10:
            set_to_max = True
            limit = count
        elif count >= total_count >> 1:
            set_to_max = True
            limit = total_count - 10
        else:
            limit = 10
        return limit, set_to_max

    def _shop_buy_amount_set_to_max(self) -> None:
        skip_first_screenshot = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(AMOUNT_MAX, offset=(50, 50), interval=3):
                continue

            if OCR_SHOP_AMOUNT.ocr(self.device.image) > 1:
                break

    def handle_port_supply_buy(self) -> bool:
        """
        Returns:
            bool: True if success to buy any or no items found.
                False if not enough coins to buy any.

        Pages:
            in: PORT_SUPPLY_CHECK
        """
        items = self.scan_all()
        if not len(items):
            logger.warning("Empty OS shop.")
            return False
        items = self.items_filter_in_os_shop(items)
        if not len(items):
            logger.warning("Nothing to buy.")
            return False
        self.os_shop_get_coins()
        skip_get_coins = True
        items.reverse()
        count = 0
        while len(items):
            logger.hr("OpsiShop buy", level=2)
            item = items.pop()
            if not skip_get_coins:
                self.os_shop_get_coins()
            if item.price > self.get_currency_coins(item):
                logger.info(f"Not enough coins to buy item: {item.name}, skip.")
                if self.is_coins_both_not_enough():
                    logger.info("Not enough coins to buy any items, stop.")
                    break
                continue
            logger.info(f"Buying item: {item.name}. In shop {item.shop_index + 1}. At pos {item.scroll_pos:.2f}.")
            self.os_shop_side_navbar_ensure(upper=item.shop_index + 1)
            OS_SHOP_SCROLL.set(item.scroll_pos, main=self, skip_first_screenshot=False)
            _item = self.os_shop_get_items_to_buy(name=item.name, price=item.price)
            if _item is None:
                logger.warning(
                    f"Item {item.name} not found in shop {item.shop_index + 1} at pos {item.scroll_pos:.2f}, skip."
                )
                continue
            if not self.check_item_count(_item):
                logger.warning(f"Get {_item.name} count error, skip.")
                continue
            if self.os_shop_buy_execute(_item):
                logger.info(f"Bought item: {_item.name}.")
                skip_get_coins = False
                count += 1
            else:
                logger.warning(f"Item {_item.name} cant be bought, skip.")
            self.device.click_record.clear()
        logger.info(f"Bought {f'{count} items' if count else 'nothing'} in port.")
        return True

    def handle_akashi_supply_buy(self, grid):
        """
        Args:
            grid: Grid where akashi stands.

        Pages:
            in: is_in_map
            out: is_in_map
        """
        self.ui_click(
            grid,
            appear_button=self.is_in_map,
            check_button=PORT_SUPPLY_CHECK,
            additional=self.handle_story_skip,
            skip_first_screenshot=True,
        )
        self.os_shop_buy(select_func=self.os_shop_get_item_to_buy_in_akashi)
        self.ui_back(appear_button=PORT_SUPPLY_CHECK, check_button=self.is_in_map, skip_first_screenshot=True)

    @cached_property
    def yellow_coins_preserve(self):
        if self.is_cl1_enabled:
            return 100000
        return 35000

    def get_currency_coins(self, item):
        if item.cost == "YellowCoins":
            if get_os_reset_remain() == 0:
                return self._shop_yellow_coins - 100
            return self._shop_yellow_coins - self.yellow_coins_preserve

        if item.cost == "PurpleCoins":
            if get_os_reset_remain() == 0:
                return self._shop_purple_coins
            return self._shop_purple_coins - self.config.OS_NORMAL_PURPLE_COINS_PRESERVE
        raise ScriptError(f"Unknown OS shop currency: {item.cost}")

    def get_coins_no_limit(self, item):
        if item.cost == "YellowCoins":
            return self._shop_yellow_coins
        if item.cost == "PurpleCoins":
            return self._shop_purple_coins
        raise ScriptError(f"Unknown OS shop currency: {item.cost}")

    def is_coins_both_not_enough(self):
        if get_os_reset_remain() == 0:
            return False
        yellow = self._shop_yellow_coins < self._shop_purple_coins
        purple = self._shop_purple_coins < self.config.OS_NORMAL_PURPLE_COINS_PRESERVE
        return yellow and purple
