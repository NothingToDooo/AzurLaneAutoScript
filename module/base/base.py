import threading
import time
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module

import cv2
import numpy as np
from PIL import Image

from module.base.button import Button
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import area_offset, color_similarity_2d, crop, ensure_int, get_color, image_size, load_image
from module.combat.emotion import Emotion
from module.config.config import AzurLaneConfig
from module.device.device import Device
from module.logger import logger
from module.map_detection.utils import fit_points
from module.webui.setting import cached_class_property


class ModuleBase:
    config: AzurLaneConfig
    device: Device

    EARLY_OCR_IMPORT = False

    def __init__(self, config, device=None, task=None):
        """config 可传配置对象或配置名；device 可复用对象、按序列号新建，或省略后新建。

        task 仅供开发时绑定；未指定时使用默认配置。
        """
        if isinstance(config, AzurLaneConfig):
            self.config = config
            if task is not None:
                self.config.init_task(task)
        elif isinstance(config, str):
            self.config = AzurLaneConfig(config, task=task)
        else:
            logger.warning("Alas ModuleBase received an unknown config, assume it is AzurLaneConfig")
            self.config = config

        if isinstance(device, Device):
            self.device = device
        elif device is None:
            self.device = Device(config=self.config)
        elif isinstance(device, str):
            self.config.override(Emulator_Serial=device)
            self.device = Device(config=self.config)
        else:
            logger.warning("Alas ModuleBase received an unknown device, assume it is Device")
            self.device = device

        self.interval_timer = {}
        self.early_ocr_import()

    @cached_property
    def emotion(self) -> Emotion:
        return Emotion(config=self.config)

    def early_ocr_import(self):
        """截图是 I/O 密集，OCR 导入是 CPU 密集；后台导入可缩短启动等待。"""
        if ModuleBase.EARLY_OCR_IMPORT:
            return
        if not self.config.is_actual_task:
            logger.info("No actual task bound, skip early_ocr_import")
            return
        if self.config.task.command in ["Daemon", "OpsiDaemon"]:
            logger.info("No ocr in daemon task, skip early_ocr_import")
            return

        def do_ocr_import():
            while 1:
                if self.device.has_cached_image:
                    break
                time.sleep(0.01)

            logger.info("early_ocr_import start")
            al_ocr_class = import_module("module.ocr.al_ocr").AlOcr
            _ = al_ocr_class
            logger.info("early_ocr_import finish")

        logger.info("early_ocr_import call")
        thread = threading.Thread(target=do_ocr_import, daemon=True)
        thread.start()
        ModuleBase.EARLY_OCR_IMPORT = True

    @cached_class_property
    def worker(cls):
        """共享单线程后台池，提交的任务不得阻塞主流程。"""
        logger.hr("Creating worker")
        return ThreadPoolExecutor(1)

    def loop(self, skip_first=True, timeout=None):
        """循环产出最新截图；skip_first 可复用已有截图，timeout 可传秒数或 Timer。"""
        if timeout is not None:
            if isinstance(timeout, Timer):
                timeout.reset()
            else:
                timeout = Timer.from_seconds(timeout).start()

        while 1:
            if timeout is not None and timeout.reached():
                return

            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()

            try:
                yield self.device.image
            except AttributeError:
                self.device.screenshot()
                yield self.device.image

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        """offset 启用模板匹配，否则按区域颜色判断；interval 限制连续触发频率。

        similarity 范围为 0～1；threshold 范围为 0～255，且越小越相似。
        """
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        if offset:
            if isinstance(offset, bool):
                offset = self.config.BUTTON_OFFSET
            appear = button.match(self.device.image, offset=offset, similarity=similarity)
        else:
            appear = button.appear_on(self.device.image, threshold=threshold)

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def match_template_color(self, button, offset=(20, 20), interval=0, similarity=0.85, threshold=30):
        """先匹配模板再校验颜色；interval 限制连续触发频率。"""
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        appear = button.match_template_color(
            self.device.image, offset=offset, similarity=similarity, threshold=threshold
        )

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def appear_then_click(self, button, offset=0, interval=0, similarity=0.85, threshold=30):
        appear = self.appear(button, offset=offset, interval=interval, similarity=similarity, threshold=threshold)
        if appear:
            self.device.click(button)
        return appear

    def wait_until_appear(self, button, offset=0, skip_first_screenshot=False):
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(button, offset=offset):
                break

    def wait_until_appear_then_click(self, button, offset=0):
        self.wait_until_appear(button, offset=offset)
        self.device.click(button)

    def wait_until_disappear(self, button, offset=0):
        while 1:
            self.device.screenshot()
            if not self.appear(button, offset=offset):
                break

    def wait_until_stable(self, button, timer=None, timeout=None, skip_first_screenshot=True):
        button.reset_match_state()
        if timer is None:
            timer = Timer(0.3, count=1)
        if timeout is None:
            timeout = Timer(5, count=10)
        timeout.reset()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if button.is_match_initialized:
                if button.match(self.device.image, offset=(0, 0)):
                    if timer.reached():
                        break
                else:
                    button.load_color(self.device.image)
                    timer.reset()
            else:
                button.load_color(self.device.image)
                button.mark_match_initialized()

            if timeout.reached():
                logger.warning(f"wait_until_stable({button}) timeout")
                break

    def image_crop(self, button, copy=True):
        if isinstance(button, Button) or hasattr(button, "area"):
            return crop(self.device.image, button.area, copy=copy)
        return crop(self.device.image, button, copy=copy)

    def image_color_count(self, button, color, threshold=221, count=50):
        """判断区域内是否有超过 count 个像素达到颜色阈值；255 表示完全相同。"""
        image = button if isinstance(button, np.ndarray) else self.image_crop(button, copy=False)
        mask = color_similarity_2d(image, color=color)
        cv2.inRange(mask, threshold, 255, dst=mask)
        sum_ = cv2.countNonZero(mask)
        return sum_ > count

    def image_color_button(self, area, color, color_threshold=250, encourage=5, name="COLOR_BUTTON"):
        """在区域内查找纯色块并生成按钮；color_threshold 为 0～255，encourage 为半径。

        没有足够匹配像素时返回 None。
        """
        image = color_similarity_2d(self.image_crop(area, copy=False), color=color)
        points = np.array(np.where(image > color_threshold)).T[:, ::-1]
        if points.shape[0] < encourage**2:
            return None

        point = fit_points(points, mod=image_size(image), encourage=encourage)
        point = ensure_int(point + area[:2])
        button_area = area_offset((-encourage, -encourage, encourage, encourage), offset=point)
        color = get_color(self.device.image, button_area)
        return Button(area=button_area, color=color, button=button_area, name=name)

    def get_interval_timer(self, button, interval=5, renew=False) -> Timer:
        if hasattr(button, "name"):
            name = button.name
        elif callable(button):
            name = button.__name__
        else:
            name = str(button)

        try:
            timer = self.interval_timer[name]
            if renew and timer.limit != interval:
                timer = Timer(interval)
                self.interval_timer[name] = timer
        except KeyError:
            timer = Timer(interval)
            self.interval_timer[name] = timer
            return timer
        else:
            return timer

    def interval_reset(self, button, interval=3):
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_reset(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].reset()
            else:
                self.interval_timer[button.name] = Timer(interval).reset()

    def interval_clear(self, button, interval=3):
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_clear(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].clear()
            else:
                self.interval_timer[button.name] = Timer(interval).clear()

    _image_file = ""

    @property
    def image_file(self):
        return self._image_file

    @image_file.setter
    def image_file(self, value):
        """开发调试入口：用本地文件或 PIL 图像替换设备截图。"""
        if isinstance(value, Image.Image):
            value = np.array(value)
        elif isinstance(value, str):
            value = load_image(value)

        self.device.image = value
