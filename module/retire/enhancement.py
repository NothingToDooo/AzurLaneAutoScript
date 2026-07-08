from dataclasses import dataclass, field
from random import choice

from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.exception import GameStuckError, ScriptError
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.retire import assets as retire_assets
from module.retire.dock import Dock

VALID_SHIP_TYPES = ["dd", "ss", "cl", "ca", "bb", "cv", "repair", "others"]
OCR_DOCK_AMOUNT = DigitCounter(retire_assets.DOCK_AMOUNT, letter=(255, 255, 255), threshold=192)
TOO_MANY_ENHANCE_STATE_TRANSITIONS_MESSAGE = "Too many state transitions"
UNKNOWN_ENHANCE_STATE_FUNCTION_TEMPLATE = "Unknown state function: {state}"


@dataclass(slots=True)
class _EnhanceChooseContext:
    ship_count: int
    need_to_skip: bool = False
    state_list: list[str] = field(default_factory=list)


class Enhancement(Dock):
    @property
    def _retire_amount(self):
        if self.config.Retirement_RetireMode == "one_click_retire":
            return 3000
        if self.config.Retirement_RetireMode == "old_retire":
            if self.config.OldRetire_RetireAmount == "retire_all":
                return 3000
            if self.config.OldRetire_RetireAmount == "retire_10":
                return 10
        return 3000

    def _enhance_enter(self, favourite=False, ship_type=None):
        """
        Pages:
            in: page_dock
            out: page_ship_enhance

        Returns:
            bool: False with filter applied resulting
                  in empty dock.
                  Otherwise true with at least 1 card
                  available to be picked.
        """
        if favourite:
            self.dock_favourite_set(enable=True, wait_loading=False)

        if ship_type is not None:
            ship_type = str(ship_type)
            self.dock_filter_set(extra="enhanceable", index=ship_type)
        else:
            self.dock_filter_set(extra="enhanceable")

        if self.appear(retire_assets.DOCK_EMPTY, offset=(30, 30)):
            return False

        return self.dock_enter_first()

    def _enhance_quit(self):
        """
        Pages:
            in: page_ship_enhance
            out: page_dock
        """
        self.ui_back(retire_assets.DOCK_CHECK)
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_filter_set()

    def _enhance_confirm(self, skip_first_screenshot=True):
        """
        Pages:
            in: EQUIP_CONFIRM
            out: page_ship_enhance, without info_bar
        """
        confirm_timer = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(retire_assets.EQUIP_CONFIRM, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear_then_click(retire_assets.EQUIP_CONFIRM_2, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear(GET_ITEMS_1, interval=2):
                self.device.click(retire_assets.GET_ITEMS_1_RETIREMENT_SAVE)
                self.interval_reset(retire_assets.ENHANCE_CONFIRM)
                confirm_timer.reset()
                continue

            # 强化确认按钮稳定后结束。
            if self.appear(retire_assets.ENHANCE_CONFIRM, offset=(30, 30)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _enhance_state_check(self, context):
        # 检查基础条件，能继续强化时进入 ready。
        context.need_to_skip = False
        if context.ship_count <= 0:
            logger.info("Reached maximum number to check, exiting current category")
            return "state_enhance_exit"
        if not self.ship_side_navbar_ensure(bottom=4):
            return "state_enhance_check"

        self.wait_until_appear(retire_assets.ENHANCE_RECOMMEND, offset=(5, 5), skip_first_screenshot=True)
        return "state_enhance_ready"

    def _enhance_state_ready(self, _context):
        # 等待推荐强化按钮出现。
        if self.appear_then_click(retire_assets.ENHANCE_RECOMMEND, offset=(5, 5), interval=0.3):
            logger.info("Set enhancement material by recommendation.")
            return "state_enhance_recommend"

        return "state_enhance_ready"

    def _enhance_state_recommend(self, _context):
        # 判断强化素材是否已经放入槽位。
        if not retire_assets.EMPTY_ENHANCE_SLOT_PLUS.match(self.device.image):
            logger.info("Material found. Try enhancing...")
            return "state_enhance_attempt"
        if self.info_bar_count():
            logger.info("No material found for enhancement.")
            logger.info("Enhancement failed. Swiping to next ship if feasible")
            return "state_enhance_fail"

        return "state_enhance_ready"

    def _enhance_state_attempt(self, _context):
        # 等待强化确认按钮出现。
        if (
            self.appear_then_click(retire_assets.ENHANCE_CONFIRM, offset=(5, 5), interval=0.3)
            or self.appear(retire_assets.EQUIP_CONFIRM, offset=(30, 30))
            or self.info_bar_count()
            or self.handle_popup_confirm("ENHANCE")
        ):
            return "state_enhance_confirm"

        return "state_enhance_attempt"

    def _enhance_state_confirm(self, context):
        # 出现确认弹窗表示强化成功，否则视为失败。
        if self.appear(retire_assets.EQUIP_CONFIRM, offset=(30, 30)):
            logger.info("Enhancement Successful")
            self._enhance_confirm()
            return "state_enhance_success"
        if self.info_bar_count():
            logger.info("Enhancement impossible, ship currently in battle. Swiping to next ship if feasible")
            context.need_to_skip = True
            return "state_enhance_fail"
        if self.handle_popup_confirm("ENHANCE"):
            logger.info("Trying a temporary ship")
            return "state_enhance_confirm"

        return "state_enhance_attempt"

    def _enhance_state_fail(self, context):
        # 避免断网导致误判。
        if self.appear(retire_assets.EQUIP_CONFIRM, offset=(30, 30)):
            return "state_enhance_confirm"

        # 尝试滑到下一艘船。
        if self.ship_view_next(check_button=retire_assets.ENHANCE_RECOMMEND):
            if not context.need_to_skip:
                context.ship_count -= 1
            return "state_enhance_check"
        # 避免断网导致误判。
        if self.appear(retire_assets.EQUIP_CONFIRM, offset=(30, 30)):
            return "state_enhance_confirm"
        logger.info("Swiped failed, exiting current category")
        return "state_enhance_exit"

    @staticmethod
    def _enhance_state_success(_context):
        return True

    @staticmethod
    def _enhance_state_exit(_context):
        return False

    def _enhance_state_handlers(self):
        return {
            "state_enhance_check": self._enhance_state_check,
            "state_enhance_ready": self._enhance_state_ready,
            "state_enhance_recommend": self._enhance_state_recommend,
            "state_enhance_attempt": self._enhance_state_attempt,
            "state_enhance_confirm": self._enhance_state_confirm,
            "state_enhance_fail": self._enhance_state_fail,
            "state_enhance_success": self._enhance_state_success,
            "state_enhance_exit": self._enhance_state_exit,
        }

    def _clear_enhance_state_click_record(self, state_list):
        if state_list[-2:] == ["state_enhance_recommend", "state_enhance_fail"]:
            names = ["ENHANCE_RECOMMEND", "SHIP_SWIPE"]
        elif state_list[-3:] == ["state_enhance_attempt", "state_enhance_confirm", "state_enhance_fail"]:
            names = ["ENHANCE_RECOMMEND", "SHIP_SWIPE", "ENHANCE_CONFIRM"]
        else:
            state_list.clear()
            return

        while self.device.click_record and self.device.click_record[-1] in names:
            self.device.click_record.pop()
        state_list.clear()

    @staticmethod
    def _check_enhance_state_loop(state_list):
        if len(state_list) <= 30:
            return
        logger.critical(f"Too many state transitions: {state_list}")
        raise GameStuckError(TOO_MANY_ENHANCE_STATE_TRANSITIONS_MESSAGE)

    @staticmethod
    def _run_enhance_state(handlers, state, context):
        try:
            handler = handlers[state]
        except KeyError as e:
            message = UNKNOWN_ENHANCE_STATE_FUNCTION_TEMPLATE.format(state=state)
            logger.warning(message)
            raise ScriptError(message) from e
        return handler(context)

    def _enhance_choose(self, ship_count, skip_first_screenshot=True):
        """
        Refactor the implementation.
        Divided the enhancement process into
        several state functions. Use a DFA method
        to call those functions according to
        current state. Each state corresponds to
        a function with the same name.

        Pages:
            in: page_ship_enhance
            out: page_ship_enhance

        Args:
            ship_count (int): ship_count, must be
            non-zero positive integer

        Returns:
            True if able to enhance otherwise False
            Always paired with current ship_count
        """
        context = _EnhanceChooseContext(ship_count=ship_count)
        handlers = self._enhance_state_handlers()
        state = "state_enhance_check"
        while isinstance(state, str):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            logger.info(f"Call state function: {state}")

            if state == "state_enhance_check":
                self._clear_enhance_state_click_record(context.state_list)
            context.state_list.append(state)
            self._check_enhance_state_loop(context.state_list)
            state = self._run_enhance_state(handlers, state, context)

        return state, context.ship_count

    def enhance_ships(self, favourite=None):
        """
        Enhance target ships by specified order
        of types listed in ENHANCE_ORDER_STRING

        Invalid types are treated as requesting
        from ALAS to choose a valid one at random

        Pages:
            in: page_dock
            out: page_dock

        Args:
            favourite (bool):

        Returns:
            int: total enhanced
        """
        if favourite is None:
            favourite = self.config.Enhance_ShipToEnhance == "favourite"

        logger.hr("Enhancement by type")
        total = 0

        ship_types = self._enhance_ship_types()
        logger.attr("Enhance Order", ship_types)

        available_ship_types = self._available_enhance_ship_types(ship_types)
        for requested_ship_type in ship_types:
            ship_type = self._resolve_enhance_ship_type(requested_ship_type, available_ship_types)
            if ship_type is False:
                continue

            total += self._enhance_ship_type(favourite=favourite, ship_type=ship_type, total=total)

        self._enhance_quit()
        return total

    def _enhance_ship_types(self):
        if self.config.Enhance_Filter is None:
            return [None]

        ship_types = [ship_type.strip().lower() for ship_type in self.config.Enhance_Filter.split(">")]
        ship_types = list(filter("".__ne__, ship_types))
        if not ship_types:
            return [None]
        return ship_types

    @staticmethod
    def _available_enhance_ship_types(ship_types):
        available_ship_types = VALID_SHIP_TYPES.copy()
        for ship_type in ship_types:
            if ship_type in available_ship_types:
                available_ship_types.remove(ship_type)
        return available_ship_types

    @staticmethod
    def _resolve_enhance_ship_type(requested_ship_type, available_ship_types):
        if requested_ship_type is None or requested_ship_type in VALID_SHIP_TYPES:
            return requested_ship_type
        if not available_ship_types:
            logger.info("No more ship types for ALAS to choose from, skipping iteration")
            return False

        ship_type = choice(available_ship_types)
        available_ship_types.remove(ship_type)
        return ship_type

    def _enhance_ship_type(self, favourite, ship_type, total):
        logger.info(f"Favourite={favourite}, Ship Type={ship_type}")

        if not self._enhance_enter(favourite=favourite, ship_type=ship_type):
            logger.hr(f"Dock Empty by ship type {ship_type}")
            return 0

        enhanced = 0
        current_count = self.config.Enhance_CheckPerCategory
        while 1:
            choose_result, current_count = self._enhance_choose(ship_count=current_count)
            if not choose_result:
                break
            enhanced += 10
            if total + enhanced >= self._retire_amount:
                break
        self.ui_back(retire_assets.DOCK_CHECK)
        return enhanced

    def _enhance_handler(self):
        """
        Pages:
            in: RETIRE_APPEAR
            out:

        Returns:
            tuple(int, int): (enhance turn count, remaining dock amount)

        Pages:
            in: DOCK_CHECK
            out: the page before retirement popup
        """
        total = self.enhance_ships()
        _, remain, _ = OCR_DOCK_AMOUNT.ocr(self.device.image)

        self.dock_quit()
        self.config.DOCK_FULL_TRIGGERED = True

        return total, remain
