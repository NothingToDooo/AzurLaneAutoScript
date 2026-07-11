from datetime import datetime

import numpy as np

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import get_color
from module.config.utils import get_server_next_update
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter
from module.os_handler import assets as os_assets
from module.os_handler.map_event import MapEventHandler
from module.statistics.item import Item, ItemGrid
from module.ui.assets import OS_CHECK
from module.ui.ui import UI

OCR_ACTION_POINT_REMAIN = Digit(os_assets.ACTION_POINT_REMAIN, letter=(255, 219, 66), name="OCR_ACTION_POINT_REMAIN")
OCR_ACTION_POINT_REMAIN_OS = Digit(
    os_assets.ACTION_POINT_REMAIN_OS, letter=(239, 239, 239), threshold=160, name="OCR_SHOP_YELLOW_COINS_OS"
)

OCR_OS_ADAPTABILITY = Digit(
    [os_assets.OS_ADAPTABILITY_ATTACK, os_assets.OS_ADAPTABILITY_DURABILITY, os_assets.OS_ADAPTABILITY_RECOVER],
    letter=(231, 235, 239),
    lang="cnocr",
    name="OCR_OS_ADAPTABILITY",
)


class ActionPointBuyCounter(DigitCounter):
    def after_process(self, result):
        result = super().after_process(result)

        # 可能的结果：0/5、05。
        if result == "05":
            result = "0/5"

        return result


OCR_ACTION_POINT_BUY_REMAIN = ActionPointBuyCounter(
    os_assets.ACTION_POINT_BUY_REMAIN, letter=(148, 247, 99), lang="cnocr", name="OCR_ACTION_POINT_BUY_REMAIN"
)


class ActionPointItem(Item):
    def predict_valid(self):
        return True


ACTION_POINT_GRID = ButtonGrid(
    origin=(323, 274), delta=(173, 0), button_shape=(115, 115), grid_shape=(4, 1), name="ACTION_POINT_GRID"
)
ACTION_POINT_ITEMS = ItemGrid(ACTION_POINT_GRID, templates={}, amount_area=(43, 89, 113, 113))
ACTION_POINT_ITEMS.item_class = ActionPointItem
ACTION_POINTS_COST = {
    1: 5,
    2: 10,
    3: 15,
    4: 20,
    5: 30,
    6: 40,
}
ACTION_POINTS_COST_OBSCURE = {
    1: 10,  # 实际上 CL1 没有隐秘海域。
    2: 10,
    3: 20,
    4: 20,
    5: 40,
    6: 40,
}
ACTION_POINTS_COST_ABYSSAL = {
    1: 80,
    2: 80,
    3: 80,  # 实际上 CL4 以下没有深渊海域。
    4: 80,
    5: 100,
    6: 100,
}
ACTION_POINTS_BUY = {
    1: 4000,
    2: 2000,
    3: 2000,
    4: 1000,
    5: 1000,
}
ACTION_POINT_BOX = {
    0: 0,
    1: 20,
    2: 50,
    3: 100,
}


class ActionPointLimit(Exception):
    pass


class ActionPointHandler(UI, MapEventHandler):
    def __init__(self, *args, **kwargs):
        self._action_point_box = [0, 0, 0, 0]
        self._action_point_current = 0
        self._action_point_total = 0
        super().__init__(*args, **kwargs)

    def _is_in_action_point(self):
        return self.appear(os_assets.ACTION_POINT_USE, offset=(20, 20))

    def is_current_ap_visible(self):
        return self.match_template_color(os_assets.CURRENT_AP_CHECK, offset=(40, 5), threshold=15)

    def action_point_use(self):
        prev = self._action_point_current
        self.interval_clear(os_assets.ACTION_POINT_USE)
        for _ in self.loop():
            if self.appear_then_click(os_assets.ACTION_POINT_USE, offset=(20, 20), interval=3):
                self.device.sleep(0.3)
                continue

            if self.handle_popup_confirm("ACTION_POINT_USE"):
                continue

            self.action_point_safe_get()
            if self._action_point_current > prev:
                break

    def action_point_update(self):
        items = ACTION_POINT_ITEMS.predict(self.device.image, name=False, amount=True)
        box = [item.amount for item in items]
        current = OCR_ACTION_POINT_REMAIN.ocr(self.device.image)
        total = current
        if self.config.OS_ACTION_POINT_BOX_USE:
            total += np.sum(np.array(box) * tuple(ACTION_POINT_BOX.values()))
        oil = box[0]

        logger.info(f"Action points: {current}({total}), oil: {oil}")
        self._action_point_current = current
        self._action_point_box = box
        self._action_point_total = total
        # 处理溢出。
        if total > 3000:
            self.config.override(OpsiGeneral_DoRandomMapEvent=False)

    def action_point_safe_get(self):
        self._wait_current_ap_visible()
        self._wait_reliable_action_point()

    def _wait_current_ap_visible(self):
        timeout = Timer(3, count=6).start()
        for _ in self.loop():
            # 结束。
            if self.is_current_ap_visible():
                break
            if timeout.reached():
                logger.warning("Get action points timeout, wait is_current_ap_visible timeout")
                break
            # 行动力弹窗上方可能强制出现地图事件。
            if self.handle_map_event():
                timeout.reset()
                continue

    def _is_reliable_action_point(self):
        # 当前行动力过高时，大概率是 OCR 误判。
        if self._action_point_current > 600:
            return False

        oil, boxes = self._action_point_box[0], self._action_point_box[1:]
        # 有行动力箱时，石油读数也需要加载完成。
        if sum(boxes) > 0:
            return oil > 100
        # 或者有石油。页面未完全加载时可能识别成 0 或 1。
        return oil > 100

    def _wait_reliable_action_point(self):
        skip_first_screenshot = True
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("Get action points timeout")
                break
            # 行动力弹窗上方可能强制出现地图事件。
            if self.handle_map_event():
                timeout.reset()
                continue

            self.action_point_update()
            if self._is_reliable_action_point():
                break

    @staticmethod
    def action_point_get_cost(zone, pinned):
        """按 DANGEROUS、SAFE、OBSCURE、ABYSSAL、STRONGHOLD 类型计算行动力消耗。"""
        if pinned == "DANGEROUS":
            cost = ACTION_POINTS_COST[zone.hazard_level] * 2
        elif pinned == "SAFE":
            cost = ACTION_POINTS_COST[zone.hazard_level]
        elif pinned == "OBSCURE":
            cost = ACTION_POINTS_COST_OBSCURE[zone.hazard_level]
        elif pinned == "ABYSSAL":
            cost = ACTION_POINTS_COST_ABYSSAL[zone.hazard_level]
        elif pinned == "STRONGHOLD":
            cost = 200
        else:
            logger.warning(f"Unable to get AP cost from zone={zone}, pinned={pinned}, assume it costs 40.")
            cost = 40

        if zone.is_port:
            cost = 0

        return cost

    def action_point_get_active_button(self):
        """返回 0 至 3：石油、20、50、100 行动力箱。"""
        for index, item in enumerate(ACTION_POINT_GRID.buttons):
            area = item.area
            color = get_color(self.device.image, area=(area[0], area[3] + 5, area[2], area[3] + 10))
            # 选中的按钮会变蓝。
            # 选中：196，未选中：118 ~ 123。
            if color[2] > 160:
                return index

        logger.warning("Unable to find an active action point box button")
        return 1

    def action_point_set_button(self, index):
        for _ in self.loop(timeout=2):
            if self.action_point_get_active_button() == index:
                return True
            self.device.click(ACTION_POINT_GRID[index, 0])
            self.device.sleep(0.3)
        logger.warning("FSet action point button timeout")
        return False

    def action_point_get_buy_remain(self):
        """在 ACTION_POINT_USE 页面读取本周剩余购买次数。"""
        current = 0
        for _ in self.loop(timeout=1):
            current, _, total = OCR_ACTION_POINT_BUY_REMAIN.ocr(self.device.image)

            # 可能的结果：0/5、05。
            if total == 0:
                continue

            break
        else:
            logger.warning("Get action points buy remain timeout")

        return current

    def action_point_buy(self, preserve=1000):
        """在 ACTION_POINT_USE 页面用石油购买行动力，并至少保留 preserve 石油。"""
        self.action_point_set_button(0)
        current = self.action_point_get_buy_remain()
        buy_max = 5  # 当前版本每周可购买 5 次行动力。
        buy_count = buy_max - current
        buy_limit = self.config.OpsiGeneral_BuyActionPointLimit
        if buy_count >= buy_limit:
            logger.info("Reach the limit to buy action points this week")
            return False
        cost = ACTION_POINTS_BUY[current]
        oil = self._action_point_box[0]
        logger.info(f"Buy action points will cost {cost}, current oil: {oil}, preserve: {preserve}")
        if oil >= cost + preserve:
            self.action_point_use()
            return True
        logger.info("Not enough oil to buy")
        return False

    def action_point_quit(self):
        """从 ACTION_POINT_USE 返回大世界页面。"""
        for _ in self.loop():
            # 行动力弹窗有时没有黑色模糊背景，此时 ACTION_POINT_CANCEL 和 OS_CHECK 会同时出现。
            if not self.appear(os_assets.ACTION_POINT_CANCEL, offset=(20, 20)) and self.appear(
                OS_CHECK, offset=(20, 20)
            ):
                break
            if self.appear_then_click(os_assets.ACTION_POINT_CANCEL, offset=(20, 20), interval=3):
                continue
            # 行动力弹窗上方可能强制出现地图事件。
            if self.handle_map_event():
                continue

    def handle_action_point(self, zone, pinned, cost=None, keep_current_ap=True, check_rest_ap=False):
        """在 ACTION_POINT_USE 补足消耗，可为次日日常保留当前行动力。

        今日可恢复量使总量达到 200 时可跳过保留；资源不足抛出 ActionPointLimit。
        """
        if not self._is_in_action_point():
            return False

        # 行动力箱有出现动画。
        self.action_point_safe_get()
        if cost is None:
            cost = self.action_point_get_cost(zone, pinned)
        buy_checked = False

        if self._can_skip_current_ap_preserve(check_rest_ap):
            keep_current_ap = False

        self._ensure_action_point_above_preserve(keep_current_ap)

        for _ in range(12):
            if self._has_enough_action_point(cost):
                return True

            bought, buy_checked = self._try_buy_action_point(buy_checked)
            if bought:
                continue

            self._ensure_action_point_total_enough(cost)

            self._use_best_action_point_box()

        logger.warning("Failed to get action points after 12 trial")
        return False

    def _can_skip_current_ap_preserve(self, check_rest_ap):
        if not check_rest_ap:
            return False
        diff = get_server_next_update("00:00") - datetime.now()
        today_rest = int(diff.total_seconds() // 600)
        if self._action_point_current + today_rest < 200:
            return False
        logger.info(
            "The sum of the current action points and the rest action points"
            " that can be obtained today exceeds 200, skip AP check"
        )
        logger.info(f"Current={self._action_point_current}  Rest={today_rest}")
        return True

    def _raise_action_point_limit(self, message):
        logger.info(message)
        self.action_point_quit()
        raise ActionPointLimit

    def _ensure_action_point_above_preserve(self, keep_current_ap):
        if keep_current_ap and self._action_point_total <= self.config.OS_ACTION_POINT_PRESERVE:
            self._raise_action_point_limit(
                f"Reach the limit of action points, preserve={self.config.OS_ACTION_POINT_PRESERVE}"
            )

    def _has_enough_action_point(self, cost):
        if self._action_point_current < cost:
            return False
        logger.info("Having enough action points")
        self.action_point_quit()
        return True

    def _try_buy_action_point(self, buy_checked):
        if self.config.OpsiGeneral_BuyActionPointLimit <= 0 or buy_checked:
            return False, buy_checked
        if self.action_point_buy(preserve=self.config.OpsiGeneral_OilLimit):
            self.action_point_safe_get()
            return True, buy_checked
        return False, True

    def _ensure_action_point_total_enough(self, cost):
        if self._action_point_total < cost:
            self._raise_action_point_limit("Not having enough action points")

    def _action_point_box_order(self):
        boxes = []
        for index in [1, 2, 3]:
            if self._action_point_box[index] <= 0:
                continue
            if self._action_point_current + ACTION_POINT_BOX[index] >= 200:
                boxes.append(index)
            else:
                boxes.insert(0, index)
        return boxes

    def _use_best_action_point_box(self):
        boxes = self._action_point_box_order()
        if not boxes:
            self._raise_action_point_limit("No more action point boxes")
        if self._action_point_total <= self.config.OS_ACTION_POINT_PRESERVE:
            self._raise_action_point_limit(
                f"Reach the limit of action points, preserve={self.config.OS_ACTION_POINT_PRESERVE}"
            )
        self.action_point_set_button(boxes[0])
        self.action_point_use()

    def action_point_enter(self):
        """从 OS_CHECK 打开 ACTION_POINT_USE。"""
        for _ in self.loop():
            if self.appear(os_assets.ACTION_POINT_USE, offset=(20, 20)):
                break

            if self.appear(OS_CHECK, offset=(20, 20), interval=3):
                self.device.click(os_assets.ACTION_POINT_REMAIN_OS)
                continue
            if self.handle_map_event():
                # 剧情弹窗是透明的，处理剧情时可能误识别到 OS_CHECK。
                self.interval_reset(OS_CHECK)
                continue
            if self.appear_then_click(os_assets.AUTO_SEARCH_REWARD, offset=(50, 50)):
                continue

    def action_point_set(self, zone=None, pinned=None, cost=None, keep_current_ap=True, check_rest_ap=False):
        """打开行动力弹窗并按 handle_action_point 补足消耗；不足时抛出 ActionPointLimit。"""
        self.action_point_enter()
        if not self.handle_action_point(zone, pinned, cost, keep_current_ap, check_rest_ap):
            return False

        for _ in self.loop():
            if self.appear(os_assets.IN_MAP, offset=(200, 5)):
                break

        return True

    def action_point_check(self, amount):
        self.action_point_enter()
        self.action_point_safe_get()

        enough = self._action_point_total > amount
        if enough:
            logger.info(f"Having {amount} action points")
        else:
            logger.info(f"Not having {amount} action points")

        self.action_point_quit()
        for _ in self.loop():
            if self.appear(os_assets.IN_MAP, offset=(200, 5)):
                break

        return enough
