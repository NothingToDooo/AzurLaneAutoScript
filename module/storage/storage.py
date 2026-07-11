import numpy as np

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Digit
from module.retire.assets import EQUIP_CONFIRM, EQUIP_CONFIRM_2
from module.shop.assets import AMOUNT_MINUS, AMOUNT_PLUS
from module.statistics.item import ItemGrid
from module.storage import assets as storage_assets
from module.storage.ui import StorageUI
from module.ui.assets import BACK_ARROW, STORAGE_CHECK
from module.ui.scroll import Scroll

MATERIAL_SCROLL = Scroll(storage_assets.METERIAL_SCROLL, color=(247, 211, 66))

EQUIPMENT_GRIDS = ButtonGrid(
    origin=(140, 88), delta=(159, 178), button_shape=(124, 124), grid_shape=(7, 3), name="EQUIPMENT"
)
EQUIPMENT_ITEMS = ItemGrid(EQUIPMENT_GRIDS, templates={}, amount_area=(90, 98, 123, 123))
OCR_DISASSEMBLE_COUNT = Digit(storage_assets.DISASSEMBLE_COUNT_OCR, letter=(235, 235, 235))


class StorageFull(Exception):
    pass


UNKNOWN_BOX_TEMPLATE_RARITY_TEMPLATE = "Unknown box template rarity: {rarity}"


class StorageHandler(StorageUI):
    storage_has_boxes = True

    @staticmethod
    def _storage_box_template(rarity):
        if rarity == 1:
            return storage_assets.TEMPLATE_BOX_T1
        if rarity == 2:
            return storage_assets.TEMPLATE_BOX_T2
        if rarity == 3:
            return storage_assets.TEMPLATE_BOX_T3
        if rarity == 4:
            return storage_assets.TEMPLATE_BOX_T4
        message = UNKNOWN_BOX_TEMPLATE_RARITY_TEMPLATE.format(rarity=rarity)
        raise ScriptError(message)

    def _handle_use_box_amount(self, amount):
        """在数量确认页设置单次开箱数；箱子不足时实际值可能小于请求值。"""
        logger.info("Set box amount")

        # 复用商店数量选择的识别逻辑。
        ocr = Digit(storage_assets.BOX_AMOUNT_OCR, letter=(239, 239, 239), name="OCR_SHOP_AMOUNT")
        index_offset = (40, 50)
        self._wait_use_box_amount_buttons(index_offset)
        current = self._wait_use_box_amount_ocr(ocr, amount)
        return self._adjust_use_box_amount(ocr, amount, current)

    def _wait_use_box_amount_buttons(self, index_offset) -> None:
        timeout = Timer(1, count=3).start()
        for _ in self.loop():
            # -/+ 按钮可能偏移，这里沿用船坞 OCR 的定位方式提高识别稳定性。
            if self.appear(AMOUNT_MINUS, offset=index_offset) and self.appear(AMOUNT_PLUS, offset=index_offset):
                break
            if timeout.reached():
                logger.warning("Wait AMOUNT_MINUS AMOUNT_PLUS timeout")
                break

    def _wait_use_box_amount_ocr(self, ocr, amount: int) -> int:
        current = 0
        timeout = Timer(1, count=3).start()
        for _ in self.loop():
            current = ocr.ocr(self.device.image)
            if 1 <= current <= amount + 10:
                break
            if timeout.reached():
                logger.warning("Wait box amount timeout")
                break
        return current

    def _adjust_use_box_amount(self, ocr, amount: int, current: int) -> int:
        logger.info(f"Set box amount: {amount}")
        skip_first = True
        retry = Timer(1, count=2)
        click_count = 0
        for _ in self.loop():
            if skip_first:
                skip_first = False
            else:
                current = ocr.ocr(self.device.image)
            diff = amount - current
            if diff == 0:
                break
            if click_count >= 2:
                logger.warning(f"Box amount stuck at {current}, requested {amount} but only {current} available")
                break

            if retry.reached():
                button = AMOUNT_PLUS if diff > 0 else AMOUNT_MINUS
                self.device.multi_click(button, n=abs(diff), interval=(0.1, 0.2))
                click_count += 1
                retry.reset()

        logger.info(f"Box amount set to {current}")
        return current

    def _storage_use_one_box(self, button, amount=1):
        """在材料页使用一组装备箱，返回可能不精确的实际数量。

        仓库已满时关闭弹窗并抛出 StorageFull；结束后仍在材料页。
        """
        logger.hr("Use one box")
        success = False
        used = 0
        self.interval_clear(
            [
                storage_assets.MATERIAL_CHECK,
                storage_assets.BOX_USE,
                GET_ITEMS_1,
                GET_ITEMS_2,
                storage_assets.EQUIPMENT_FULL,
                storage_assets.BOX_AMOUNT_CONFIRM,
                EQUIP_CONFIRM,
                EQUIP_CONFIRM_2,
            ]
        )

        for _ in self.loop():
            if self._storage_use_box_finished(success=success):
                break
            if self._handle_storage_box_entry(button):
                continue

            actual = self._handle_storage_box_amount_confirm(amount)
            if actual is not None:
                used = actual
                continue

            confirm_success = self._handle_storage_box_confirm()
            if confirm_success is not None:
                success = success or confirm_success
                continue

            self._raise_if_storage_box_full()

        logger.info(f"Used {used} box(es)")
        return used

    def _storage_use_box_finished(self, *, success: bool) -> bool:
        return success and self._storage_in_material() and not self.appear(EQUIP_CONFIRM_2, offset=(20, 20))

    def _handle_storage_box_entry(self, button) -> bool:
        if self._storage_in_material(interval=5):
            self.device.click(button)
            return True
        if self.appear_then_click(storage_assets.BOX_USE, offset=(-330, -20, 20, 20), interval=5):
            self.interval_reset(storage_assets.MATERIAL_CHECK)
            return True
        return self._handle_storage_box_get_items()

    def _handle_storage_box_get_items(self) -> bool:
        for button in (GET_ITEMS_1, GET_ITEMS_2):
            if self.appear(button, offset=(5, 5), interval=5):
                logger.info(f"{button} -> {storage_assets.MATERIAL_ENTER}")
                self.device.click(storage_assets.MATERIAL_ENTER)
                self.interval_reset(storage_assets.MATERIAL_CHECK)
                return True
        return False

    def _handle_storage_box_amount_confirm(self, amount: int) -> int | None:
        # 开箱动画会覆盖确认按钮，用颜色模板等待确认按钮真正露出。
        if not self.match_template_color(storage_assets.BOX_AMOUNT_CONFIRM, offset=(20, 20), interval=5):
            return None

        actual = self._handle_use_box_amount(amount)
        self.device.click(storage_assets.BOX_AMOUNT_CONFIRM)
        self.interval_reset(storage_assets.BOX_AMOUNT_CONFIRM)
        return actual

    def _handle_storage_box_confirm(self) -> bool | None:
        if self.appear_then_click(EQUIP_CONFIRM, offset=(20, 20), interval=5):
            self.interval_reset(storage_assets.MATERIAL_CHECK)
            return False
        if self.appear_then_click(EQUIP_CONFIRM_2, offset=(20, 20), interval=5):
            self.interval_reset(storage_assets.MATERIAL_CHECK)
            self.interval_clear([GET_ITEMS_1, GET_ITEMS_2])
            # GET_ITEMS_* 不会立即出现，因此把 EQUIP_CONFIRM_2 视作最后一步。
            return True
        return None

    def _raise_if_storage_box_full(self) -> None:
        if not self.appear(storage_assets.EQUIPMENT_FULL, offset=(20, 20)):
            return

        logger.info("Storage full")
        self.ui_click(
            storage_assets.MATERIAL_ENTER,
            check_button=self._storage_in_material,
            appear_button=storage_assets.EQUIPMENT_FULL,
            retry_wait=3,
            skip_first_screenshot=True,
        )
        raise StorageFull

    def _storage_use_box_in_page(self, rarity, amount, skip_first_screenshot=False):
        """在当前材料页最多使用 amount 个箱子，返回可能不精确的实际数量。"""
        used = 0
        timeout = Timer(1.5, count=3).start()
        while 1:
            logger.attr("Used", f"{used}/{amount}")
            if used >= amount:
                logger.info("Reached target amount, stop")
                break
            if timeout.reached():
                logger.info("No more boxes on this page, stop")
                break

            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            image = rgb2gray(self.device.image)
            sim, box_button = self._storage_box_template(rarity).match_result(image)
            if sim > 0.9:
                used += self._storage_use_one_box(box_button, amount)
                continue
            logger.info("No boxes found")
            continue

        return used

    def _storage_use_box_execute(self, rarity=1, amount=10):
        """在材料页最多使用 amount 个 T1 至 T4 箱子，返回可能不精确的实际数量。

        仓库已满时抛出 StorageFull，页面保持在材料页。
        """
        logger.hr("Use Box", level=2)
        used = 0

        if MATERIAL_SCROLL.appear(main=self):
            if rarity == 1:
                # T1 箱始终位于底部。
                MATERIAL_SCROLL.set_bottom(main=self)
            else:
                MATERIAL_SCROLL.set_top(main=self)

            while 1:
                logger.hr("Use boxes in page")
                used += self._storage_use_box_in_page(rarity=rarity, amount=max(amount - used, 0))
                if used >= amount:
                    break
                if MATERIAL_SCROLL.at_bottom(main=self):
                    logger.info("Scroll bar reached end, stop")
                    break
                MATERIAL_SCROLL.next_page(main=self)
        else:
            logger.hr("Use boxes in page")
            used += self._storage_use_box_in_page(rarity=rarity, amount=amount)

        return used

    def _storage_disassemble_equipment_execute_once(self, amount=40):
        """在拆解页执行一轮，单轮最多拆解 40 件，并返回实际数量。"""
        amount = min(amount, 40)
        self.interval_clear(
            [
                storage_assets.DISASSEMBLE_CONFIRM,
                storage_assets.DISASSEMBLE_POPUP_CONFIRM,
                GET_ITEMS_1,
                GET_ITEMS_2,
                storage_assets.DISASSEMBLE_CANCEL,
            ]
        )
        logger.info(f"Disassemble once, expected amount: {amount}")

        self._clear_disassemble_reward_popups()
        self.interval_clear(
            [
                GET_ITEMS_1,
                GET_ITEMS_2,
            ]
        )
        self.wait_until_stable(storage_assets.MATERIAL_STABLE_CHECK)

        amount = self._select_disassemble_equipment(amount)
        if amount <= 0:
            return 0

        disassembled = self._wait_disassemble_count(amount)
        logger.info(f"Disassemble once, actual amount: {disassembled}")
        if disassembled <= 0:
            logger.warning("No items selected to disassemble")
            return 0

        return self._confirm_disassemble_equipment(disassembled)

    def _clear_disassemble_reward_popups(self) -> None:
        for _ in self.loop():
            if self._handle_disassemble_get_items():
                continue
            if self.handle_info_bar():
                continue
            if self.appear(storage_assets.DISASSEMBLE_CANCEL, offset=(20, 20)):
                break

    def _handle_disassemble_get_items(self) -> bool:
        for button in (GET_ITEMS_1, GET_ITEMS_2):
            if self.appear(button, offset=(5, 5), interval=3):
                logger.info(f"{button} -> {storage_assets.DISASSEMBLE_CONFIRM}")
                self.device.click(storage_assets.DISASSEMBLE_CONFIRM)
                return True
        return False

    def _select_disassemble_equipment(self, amount: int) -> int:
        items = EQUIPMENT_ITEMS.predict(self.device.image, name=False, amount=True)
        if not len(items):
            logger.warning("No items in storage to disassemble")
            return 0
        cumsum = np.cumsum([item.amount for item in items])
        for item, total in zip(items, cumsum, strict=True):
            if item.amount <= 0:
                continue
            self.device.click(item)
            self.device.click_record.pop()
            if total >= amount:
                amount = total
                break
        return int(min(cumsum[-1], amount))

    def _wait_disassemble_count(self, amount: int) -> int:
        logger.info(f"Disassemble once, in_storage amount: {amount}")
        timeout = Timer(1, count=2).start()
        prev_disassemble = 0
        while 1:
            self.device.screenshot()
            disassembled = OCR_DISASSEMBLE_COUNT.ocr(self.device.image)
            if disassembled >= amount:
                logger.info("Disassemble amount reached expected amount")
                break
            if timeout.reached():
                logger.warning("Wait disassemble amount timeout")
                break
            if disassembled > prev_disassemble:
                prev_disassemble = disassembled
                timeout.reset()
        return disassembled

    def _confirm_disassemble_equipment(self, disassembled: int) -> int:
        skip_first_screenshot = True
        click_count = 0
        success = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if click_count >= 3:
                # 可能没有选中任何装备，外层会重新尝试选择。
                logger.warning("Failed to confirm disassemble after 3 trial")
                disassembled = 0
                break
            if success and self.appear(storage_assets.DISASSEMBLE_CANCEL, offset=(20, 20)):
                self.wait_until_stable(storage_assets.MATERIAL_STABLE_CHECK)
                break

            if self.appear_then_click(storage_assets.DISASSEMBLE_CONFIRM, offset=(20, 20), interval=5):
                click_count += 1
                continue
            if self.appear_then_click(storage_assets.DISASSEMBLE_POPUP_CONFIRM, offset=(-15, -5, 5, 70), interval=5):
                # 2025.05.20 起，装备拆解不再弹出 GET_ITEMS。
                success = True
                continue
            if self.handle_popup_confirm("DISASSEMBLE"):
                continue
            if self._handle_disassemble_get_items():
                success = True
                continue

        return disassembled

    def _storage_disassemble_equipment_execute(self, rarity=1, amount=40):
        """在拆解页按 1 至 5 的稀有度拆解；堆叠选择可能使实际数量超过目标。"""
        disassembled = 0
        self.equipment_filter_set(rarity=rarity)
        if MATERIAL_SCROLL.appear(main=self):
            MATERIAL_SCROLL.set_top(main=self)

        while 1:
            logger.hr("Disassemble once")
            logger.attr("Disassembled", f"{disassembled}/{amount}")
            if self.appear(storage_assets.EQUIPMENT_EMPTY, offset=(20, 20)):
                logger.info("Equipment list empty, stop")
                break
            if disassembled >= amount:
                logger.info("Reached target amount, stop")
                break

            if amount - disassembled < 40:
                disassembled += self._storage_disassemble_equipment_execute_once(amount=amount - disassembled)
            else:
                disassembled += self._storage_disassemble_equipment_execute_once()

        self.equipment_filter_set()
        return disassembled

    def storage_disassemble_equipment(self, rarity=1, amount=15):
        """从任意页面拆解目标数量的 1 至 4 稀有度装备；不足时先开箱。

        堆叠选择可能超过目标，结束于仓库拆解页并返回实际数量。
        """
        logger.hr("Disassemble Equipment", level=2)
        self.ui_goto_storage()
        # 不需要切换装备中开关，它不影响拆解。
        # 也不需要单独等待仓库稳定，筛选确认会处理。
        disassembled = 0
        while 1:
            logger.attr("Total_Disassemble", f"{disassembled}/{amount}")
            if disassembled >= amount:
                logger.info("Reached total target amount, stop")
                break

            self._storage_enter_material()
            try:
                boxes = self._storage_use_box_execute(rarity=rarity, amount=amount - disassembled)
                if boxes <= 0:
                    logger.warning("No more boxes to use, disassemble equipment end")
                    self.storage_has_boxes = False
                    break
                # 2025.05.20 起，箱子里的装备会自动拆解。
                disassembled += boxes
                continue
            except StorageFull:
                pass
            self._storage_enter_disassemble()
            equip = self._storage_disassemble_equipment_execute(rarity=rarity, amount=amount)
            disassembled += equip
            if equip <= 0:
                logger.warning(
                    "StorageFull but unable to disassemble, "
                    "probably because storage is full of rare equipments or above, "
                    "disassemble equipment end"
                )
                logger.warning("Please manually disassemble some equipments to free up storage")
                self.storage_has_boxes = False
                break

        return disassembled

    def storage_use_box(self, rarity=1, amount=40):
        """从任意页面清理仓库后最多使用 amount 个 1 至 4 稀有度箱子。

        结束于材料页并返回实际开箱数。
        """
        logger.hr("Use boxes", level=2)
        self.ui_goto_storage()
        self._storage_enter_material()
        self._wait_until_storage_stable()

        used = 0
        while 1:
            self._storage_enter_disassemble()
            self._storage_disassemble_equipment_execute(rarity=rarity, amount=amount)

            logger.attr("Total_Used", f"{used}/{amount}")
            if used >= amount:
                logger.info("Reached total target amount, stop")
                break

            boxes = 0
            try:
                self._storage_enter_material()
                boxes = self._storage_use_box_execute(rarity=rarity, amount=amount - used)
                used += boxes
                if boxes <= 0:
                    logger.warning("No more boxes to use, use boxes end")
                    self.storage_has_boxes = False
                    break
            except StorageFull:
                if boxes <= 0:
                    logger.warning(
                        "Unable to use boxes because storage full, "
                        "probably because storage is full of rare equipments or above, "
                        "use boxes end"
                    )
                    logger.warning("Please manually disassemble some equipments to free up storage")
                    self.storage_has_boxes = False
                    break

        return used

    def handle_storage_full(self, rarity=1, amount=40):
        """出现仓库已满弹窗时拆解 1 至 4 稀有度装备，并恢复到原页面。"""
        if not self.appear(storage_assets.EQUIPMENT_FULL, offset=(30, 30), interval=2):
            return False

        logger.info("handle_storage_full")
        self.ui_click(
            storage_assets.EQUIPMENT_FULL,
            check_button=storage_assets.DISASSEMBLE_CANCEL,
            skip_first_screenshot=True,
            retry_wait=3,
        )
        disassembled = self._storage_disassemble_equipment_execute(rarity=rarity, amount=amount)
        if disassembled <= 0:
            logger.warning("Storage full but unable to disassemble any equipment")

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(storage_assets.DISASSEMBLE_CANCEL, offset=(30, 30), interval=3):
                continue
            if self.appear(storage_assets.DISASSEMBLE, offset=(30, 30), interval=3):
                self.device.click(BACK_ARROW)
                continue

            if not self.appear(STORAGE_CHECK, offset=(30, 30)):
                break

        return True
