from datetime import datetime, timedelta

import numpy as np

from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.exception import GameTooManyClickError
from module.logger import logger
from module.ocr.ocr import Duration
from module.research import assets as research_assets
from module.research.project import get_research_finished
from module.research.rqueue import ResearchQueue
from module.research.selector import RESEARCH_ENTRANCE, ResearchSelector
from module.storage.storage import StorageHandler
from module.ui.assets import RESEARCH_CHECK
from module.ui.page import page_research

OCR_DURATION = Duration(
    research_assets.RESEARCH_LAB_DURATION_REMAIN,
    letter=(255, 255, 255),
    threshold=64,
    name="RESEARCH_LAB_DURATION_REMAIN",
)


class RewardResearch(ResearchSelector, ResearchQueue, StorageHandler):
    _research_project_offset = 0
    _research_finished_index = 2
    research_project_started = None
    enforce = False
    end_time = None

    def research_has_finished(self):
        """兼容游戏偶尔未把已完成科研自动居中的问题。"""
        index = get_research_finished(self.device.image)
        if index is not None:
            logger.attr("Research_finished", index)
            self._research_finished_index = index
            return True
        return False

    def research_reset(self, skip_first_screenshot=True):
        if not self.appear(research_assets.RESET_AVAILABLE, threshold=10):
            logger.info("Research reset unavailable")
            return False

        logger.info("Research reset")
        executed = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(research_assets.RESET_AVAILABLE, interval=10, threshold=10):
                continue
            if self.handle_popup_confirm("RESEARCH_RESET"):
                executed = True
                continue

            if executed and self.is_in_research():
                self.ensure_no_info_bar(timeout=3)
                self.ensure_research_stable()
                break

        self._research_project_offset = 0
        return True

    def research_enforce(self, add_queue=True):
        """强制选择项目；第六个项目不能加入队列。"""
        if not self.enforce:
            logger.info("Enforce choosing research project")
            self.enforce = True
            return self.research_select(self.research_sort_filter(self.enforce), add_queue=add_queue)
        return True

    def _research_select_priority(self, project, add_queue):
        result = None
        if project == "reset":
            if self.research_reset():
                result = False
        elif isinstance(project, str):
            if project == "shortest":
                self.research_select(self.research_sort_shortest(self.enforce), add_queue=add_queue)
            elif project == "cheapest":
                self.research_select(self.research_sort_cheapest(self.enforce), add_queue=add_queue)
            else:
                logger.warning(f"Unknown select method: {project}")
            result = True
        elif project.genre.upper() in ["C", "T"] and not self.enforce:
            result = self.research_enforce(add_queue=add_queue)
        else:
            started = self.research_project_start_with_requirements(project, add_queue=add_queue)
            if started:
                result = True
            elif started is not None and self.research_delay_check():
                logger.info("Delay research when resources not enough and queue not empty")
                result = True
        return result

    def research_select(self, priority, add_queue=True):
        """按项目或预设字符串优先级选择；重置后返回 False，第六个项目不能入队。"""
        if not len(priority):
            logger.info("No research project satisfies current filter")
            return self.research_enforce(add_queue=add_queue)
        for project in priority:
            result = self._research_select_priority(project, add_queue=add_queue)
            if result is not None:
                return result

        logger.info("No research project started")
        return self.research_enforce(add_queue=add_queue)

    def research_delay_check(self):
        """判断资源不足时能否延后科研。"""
        if self.config.Research_AllowDelay:
            slot = self.get_queue_slot()
            if slot < 4:
                return True
            if slot == 4:
                now = datetime.now()
                end_time = self.end_time
                if isinstance(end_time, datetime) and (end_time <= now or end_time + timedelta(minutes=-10) > now):
                    return True

        return False

    def _research_project_index(self, project):
        if isinstance(project, int):
            return project
        if project in self.projects:
            return self.projects.index(project)
        logger.warning(f"The project to start: {project} is not in known projects")
        return None

    def _research_project_unavailable_max_rgb(self):
        return np.max(rgb2gray(self.image_crop(research_assets.RESEARCH_UNAVAILABLE, copy=False)))

    def _click_research_project_if_ready(self, index, click_timer):
        # 这里不要用 interval，RESEARCH_CHECK 早在 5 秒前就出现了。
        if not (click_timer.reached() and self.is_in_research()):
            return False

        position = (index - self._research_project_offset) % 5
        logger.info(f"Project offset: {self._research_project_offset}, project {index} is at {position}")
        self.device.click(RESEARCH_ENTRANCE[position])
        self.ensure_research_stable()
        click_timer.reset()
        return True

    def _click_research_start_if_available(self, max_rgb):
        return max_rgb > 235 and self.appear_then_click(research_assets.RESEARCH_START, offset=(5, 20), interval=10)

    def _finish_research_project_start(self, project, index, add_queue):
        # RESEARCH_STOP 是半透明按钮，颜色会随背景变化。
        if add_queue:
            self.research_queue_add()
        else:
            self.research_detail_quit()
        self.research_project_started = project
        self._research_project_offset = (index - 2) % 5
        return True

    def _finish_research_project_unavailable(self, index):
        logger.info("Not enough resources to start this project")
        self.research_detail_quit()
        self.research_project_started = None
        self._research_project_offset = (index - 2) % 5
        return False

    @staticmethod
    def _raise_research_start_too_many_click():
        logger.error(
            "Unable to start a research project after 3 trail, "
            "probably because there is a research running but requirements not satisfied, "
            "or a research finished"
        )
        raise GameTooManyClickError

    def research_project_start(self, project, add_queue=True, skip_first_screenshot=True):
        """启动项目对象或 0～4 索引；未知项目返回 None，第六个项目不能入队。"""
        logger.hr("Research project start")
        logger.info(f"Research project: {project}")
        index = self._research_project_index(project)
        if index is None:
            return None
        logger.info(f"Research project: {index}")
        self.interval_clear([research_assets.RESEARCH_START])
        self.popup_interval_clear()
        available = False
        click_timer = Timer(10)
        click_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            max_rgb = self._research_project_unavailable_max_rgb()

            if self._click_research_project_if_ready(index, click_timer):
                click_count += 1
                continue
            if self._click_research_start_if_available(max_rgb):
                available = True
                continue
            if self.handle_popup_confirm("RESEARCH_START"):
                continue

            if click_count >= 3:
                self._raise_research_start_too_many_click()
            if self.appear(research_assets.RESEARCH_STOP, offset=(20, 20)):
                return self._finish_research_project_start(project, index, add_queue)
            if not available and max_rgb <= 235 and self.appear(research_assets.RESEARCH_UNAVAILABLE, offset=(5, 20)):
                return self._finish_research_project_unavailable(index)
        return False

    def research_project_start_with_requirements(self, project, add_queue=True):
        """处理要求后启动；成功、资源不足、未知项目分别返回 True、False、None。

        E 类项目可能先拆解装备。
        """
        if isinstance(project, int):
            return self.research_project_start(project, add_queue=add_queue)
        if project.genre == "E" and project.equipment_amount > 0:
            logger.info(
                f"Going to start an E series research: {project} and disassemble {project.equipment_amount} equipment"
            )
            self.research_project_start(project, add_queue=False)
            self.storage_disassemble_equipment(amount=project.equipment_amount)
            self.ui_ensure(page_research)
            self.research_project_list_init()
            result = self.research_project_start(project, add_queue=add_queue)
            if result is None:
                logger.error("Research project is missing after disassemble equipment")
            return result
        return self.research_project_start(project, add_queue=add_queue)

    def research_receive(self, skip_first_screenshot=True):
        """在稳定科研页领取完成项目；要求不满足时返回 False。"""
        logger.hr("Research receive", level=3)
        confirm_timer = Timer(1.5, count=5)
        record_button = None
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(RESEARCH_CHECK, offset=(20, 20), interval=10) and self.research_has_finished():
                self.device.click(RESEARCH_ENTRANCE[self._research_finished_index])

            if self.appear(research_assets.RESEARCH_STOP, offset=(20, 20)):
                logger.info("The research time is up, but requirements are not satisfied")
                self.research_project_started = None
                self.research_detail_quit()
                return False
            if self.appear(research_assets.RESEARCH_START, offset=(20, 20), interval=5):
                self.device.click(research_assets.RESEARCH_DETAIL_QUIT)
                continue

            appear_button = self.get_items()
            if appear_button is not None:
                if appear_button == record_button:
                    if confirm_timer.reached():
                        break
                else:
                    logger.info(f"{appear_button} appeared")
                    record_button = appear_button
                    confirm_timer.reset()

        self.ui_click(
            appear_button=self.get_items,
            click_button=research_assets.GET_ITEMS_RESEARCH_SAVE,
            check_button=self.is_in_research,
            skip_first_screenshot=True,
        )
        return True

    def queue_receive(self, skip_first_screenshot=True):
        """在队列页领取奖励，返回领取的项目数。"""
        logger.hr("Queue receive", level=1)
        total = 0
        end_confirm = Timer(1, count=3)
        item_interval = Timer(0.2, count=0)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 不加 offset，只做颜色检测。
            if self.is_in_queue() and not self.appear(research_assets.QUEUE_CLAIM_REWARD, offset=None):
                if end_confirm.reached():
                    break
            else:
                end_confirm.reset()

            if item_interval.reached():
                appear_button = self.get_items()
                if appear_button is not None:
                    self.device.click(research_assets.GET_ITEMS_RESEARCH_SAVE)
                    item_interval.reset()
                    total += 1
                    continue

            if self.appear_then_click(research_assets.QUEUE_CLAIM_REWARD, offset=None, interval=5):
                continue

        logger.info(f"Received rewards from {total} projects")
        return total

    def queue_quit(self, *args, **kwargs):
        super().queue_quit(*args, **kwargs)
        self._research_project_offset = 0

    def research_project_list_init(self, from_queue=False):
        """重置项目偏移并检测列表；从队列返回时页面已稳定。"""
        self._research_project_offset = 0
        # info_bar 消失后再截图一次，等待残影清除。
        if self.handle_info_bar():
            self.device.screenshot()
        if not from_queue:
            self.ensure_research_center_stable()
        self.research_detect()

    def research_queue_append(self, add_queue=True):
        """选择并启动项目；add_queue=False 用于不入队的第六项目。"""
        self.research_project_started = None
        for _ in range(2):
            logger.hr("Research select", level=2)
            self.research_project_list_init(from_queue=True)
            priority = self.research_sort_filter()
            result = self.research_select(priority, add_queue=add_queue)
            if result:
                break

        return self.research_project_started is not None

    def research_fill_queue(self):
        """从科研页填满队列，返回新入队数量。"""
        logger.hr("Research fill queue", level=1)
        total = 0
        for _ in range(5):
            if self.get_queue_slot() > 0:
                success = self.research_queue_append()
                if success:
                    total += 1
                else:
                    logger.info(f"Unable to start a project, stop filling queue, queue added: {total}")
                    return total
            else:
                break

        status = self.get_research_status(self.device.image)
        if "waiting" not in status:
            logger.info("Select the 6th research")
            self.research_queue_append(add_queue=False)
        else:
            logger.info("6th research already waiting")

        logger.info(f"Research queue full filled, queue added: {total}")
        return total

    @staticmethod
    def _is_6th_research_stable(status):
        if "unknown" in status:
            return False
        if "waiting" in status:
            return status.index("waiting") == 2
        return sum(s == "detail" for s in status) == 5

    def _wait_6th_research_stable(self, skip_first_screenshot):
        # 等待项目卡片加载和队列动画结束。
        timeout = Timer(2, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("receive_6th_research wait timeout")
                break

            status = self.get_research_status(self.device.image)
            if self._is_6th_research_stable(status):
                break

    def _receive_finished_6th_research(self):
        if self.research_has_finished():
            logger.info(f"6th research finished at: {self._research_finished_index}")
            return self.research_receive()
        logger.info("No research has finished")
        return True

    def _append_6th_research_if_possible(self, status, state):
        if state not in status:
            return
        if self.get_queue_slot() > 0:
            self.research_project_start(status.index(state))
            return
        logger.info(f"Queue full, stop appending {state} research")

    def _append_6th_research_from_status(self):
        status = self.get_research_status(self.device.image)
        self._append_6th_research_if_possible(status, "waiting")
        self._append_6th_research_if_possible(status, "running")

    def receive_6th_research(self, skip_first_screenshot=True):
        logger.hr("Receive 6th research", level=2)
        self._wait_6th_research_stable(skip_first_screenshot)
        if not self._receive_finished_6th_research():
            return False
        self._append_6th_research_from_status()
        return True

    def run(self):
        """从任意页面执行科研，结束于科研项目页或主页。"""
        self.ui_ensure(page_research)

        self.queue_enter()
        self.queue_receive()
        self.end_time = self.get_research_ended()
        self.queue_quit()

        self.receive_6th_research()

        self.research_fill_queue()
        slot = self.get_queue_slot()
        if slot == 5:
            self.config.task_delay(server_update=True)
            return
        if self.end_time <= datetime.now():
            self.queue_enter()
            self.end_time = self.get_research_ended()
            self.queue_quit()
        if slot == 4:
            # 资源不足时提前十分钟重试，避免科研队列空转。
            self.end_time = self.end_time + timedelta(minutes=-10)
        self.config.task_delay(target=self.end_time)
