from typing import TYPE_CHECKING, Literal

from module.base.timer import Timer
from module.base.utils import crop, rgb2gray
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3, GET_ITEMS_3_CHECK
from module.logger import logger
from module.research import assets as research_assets
from module.research.project import RESEARCH_STATUS
from module.research.series import RESEARCH_SCALING
from module.ui.assets import BACK_ARROW, RESEARCH_CHECK
from module.ui.ui import UI

if TYPE_CHECKING:
    from module.base.button import Button
    from module.base.type_alias import ImageArray

type ResearchStatus = Literal["waiting", "running", "detail", "unknown"]


class ResearchUI(UI):
    def is_in_research(self, interval: float = 0) -> bool:
        return self.appear(RESEARCH_CHECK, offset=(20, 20), interval=interval)

    def is_in_queue(self, interval: float = 0) -> bool:
        return self.appear(research_assets.QUEUE_CHECK, offset=(20, 20), interval=interval)

    def ensure_research_stable(self) -> None:
        self.wait_until_stable(research_assets.STABLE_CHECKER)

    def ensure_research_center_stable(self) -> None:
        self.wait_until_stable(research_assets.STABLE_CHECKER_CENTER)

    def queue_enter(self, *, skip_first_screenshot: bool = True) -> None:
        """从科研页进入队列页。"""
        self.ui_click(
            research_assets.RESEARCH_GOTO_QUEUE,
            check_button=self.is_in_queue,
            appear_button=self.is_in_research,
            retry_wait=1,
            skip_first_screenshot=skip_first_screenshot,
        )

    def queue_quit(self) -> None:
        """退出队列并等待科研项目页稳定。"""
        logger.info("Queue quit")
        for _ in self.loop():
            if self.is_in_research():
                break
            if self.is_in_queue(interval=3):
                self.device.click(BACK_ARROW)
                continue
            # 处理掉落弹窗。
            # 掉落应在领取时处理，但网络慢时可能延迟到这里。
            if self.appear(GET_ITEMS_1, offset=(20, 20), interval=3):
                logger.info(f"{GET_ITEMS_1} -> {research_assets.GET_ITEMS_RESEARCH_SAVE}")
                self.device.click(research_assets.GET_ITEMS_RESEARCH_SAVE)
                continue
            if self.appear(GET_ITEMS_2, offset=(20, 20), interval=3):
                logger.info(f"{GET_ITEMS_1} -> {research_assets.GET_ITEMS_RESEARCH_SAVE}")
                self.device.click(research_assets.GET_ITEMS_RESEARCH_SAVE)
                continue

        self.ensure_research_center_stable()

    def get_items(self) -> Button | None:
        if self.appear(GET_ITEMS_3, offset=(5, 5)):
            if self.image_color_count(GET_ITEMS_3_CHECK, color=(255, 255, 255), threshold=221, count=100):
                return GET_ITEMS_3
            return GET_ITEMS_2
        if self.appear(GET_ITEMS_1, offset=(5, 5)):
            return GET_ITEMS_1
        return None

    def has_items(self) -> bool:
        return self.get_items() is not None

    @staticmethod
    def get_research_status(image: ImageArray) -> list[ResearchStatus]:
        """返回五个项目的 waiting、running、detail 或 unknown 状态。"""
        out: list[ResearchStatus] = []
        for _index, status, scaling in zip(range(5), RESEARCH_STATUS, RESEARCH_SCALING, strict=True):
            info = status.crop((0, -40, 200, 0))
            piece = rgb2gray(crop(image, info.area, copy=False))
            if research_assets.TEMPLATE_WAITING.match(piece, scaling=scaling, similarity=0.75):
                out.append("waiting")
            elif research_assets.TEMPLATE_RUNNING.match(piece, scaling=scaling, similarity=0.75):
                out.append("running")
            elif research_assets.TEMPLATE_DETAIL.match(piece, scaling=scaling, similarity=0.75):
                out.append("detail")
            else:
                out.append("unknown")

        logger.info(f"Research status: {out}")
        return out

    def is_research_stabled(self) -> bool:
        return self.is_in_research() and "detail" in self.get_research_status(self.device.image)

    def research_detail_quit(self, *, skip_first_screenshot: bool = True) -> None:
        logger.info("Research detail quit")
        click_timer = Timer(10)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_research_stabled():
                break

            if (
                self.appear(research_assets.RESEARCH_UNAVAILABLE, offset=(20, 20))
                or self.appear(research_assets.RESEARCH_START, offset=(20, 20))
                or self.appear(research_assets.RESEARCH_STOP, offset=(20, 20))
            ) and click_timer.reached():
                self.device.click(research_assets.RESEARCH_DETAIL_QUIT)
                click_timer.reset()

    def research_detail_cancel(self, *, skip_first_screenshot: bool = True) -> None:
        logger.info("Research detail cancel")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_research_stabled():
                break

            if self.appear_then_click(research_assets.RESEARCH_STOP, offset=(20, 20), interval=5):
                continue
            if self.handle_popup_confirm("RESEARCH_CANCEL"):
                continue
            if self.appear(research_assets.RESEARCH_START, offset=(20, 20), interval=5):
                self.device.click(research_assets.RESEARCH_DETAIL_QUIT)
                continue
