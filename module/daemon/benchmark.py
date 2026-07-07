import time

import numpy as np
from rich.table import Table
from rich.text import Text

from module.base.utils import float2str as float2str_
from module.base.utils import random_rectangle_point
from module.campaign.campaign_ui import CampaignUI
from module.daemon.daemon_base import DaemonBase
from module.exception import RequestHumanTakeover
from module.logger import logger


def float2str(n, decimal=3):
    if not isinstance(n, (float, int)):
        return str(n)
    return float2str_(n, decimal=decimal) + "s"


class Benchmark(DaemonBase, CampaignUI):
    TEST_TOTAL = 15
    TEST_BEST = int(TEST_TOTAL * 0.8)

    def benchmark_test(self, func, *args, **kwargs):
        """
        Args:
            func: Function to test.
            *args: Passes to func.
            **kwargs: Passes to func.

        Returns:
            float: Time cost on average.
        """
        logger.hr("Benchmark test", level=2)
        logger.info(f"Testing function: {func.__name__}")
        record = []

        for n in range(1, self.TEST_TOTAL + 1):
            start = time.perf_counter()

            try:
                func(*args, **kwargs)
            except RequestHumanTakeover:
                logger.critical("RequestHumanTakeover")
                logger.warning(f"Benchmark tests failed on func: {func.__name__}")
                return "Failed"

            cost = time.perf_counter() - start
            logger.attr(f"{str(n).rjust(2, '0')}/{self.TEST_TOTAL}", f"{float2str(cost)}")
            record.append(cost)

        logger.info("Benchmark tests done")
        average = float(np.mean(np.sort(record)[: self.TEST_BEST]))
        logger.info(f"Time cost {float2str(average)} ({self.TEST_BEST} best results out of {self.TEST_TOTAL} tests)")
        return average

    @staticmethod
    def evaluate_screenshot(cost):
        if not isinstance(cost, (float, int)):
            return Text(cost, style="bold bright_red")

        if cost < 0.025:
            return Text("Insane Fast", style="bold bright_green")
        if cost < 0.100:
            return Text("Ultra Fast", style="bold bright_green")
        if cost < 0.200:
            return Text("Very Fast", style="bright_green")
        if cost < 0.300:
            return Text("Fast", style="green")
        if cost < 0.500:
            return Text("Medium", style="yellow")
        if cost < 0.750:
            return Text("Slow", style="red")
        if cost < 1.000:
            return Text("Very Slow", style="bright_red")
        return Text("Ultra Slow", style="bold bright_red")

    @staticmethod
    def evaluate_click(cost):
        if not isinstance(cost, (float, int)):
            return Text(cost, style="bold bright_red")

        if cost < 0.100:
            return Text("Fast", style="bright_green")
        if cost < 0.200:
            return Text("Medium", style="yellow")
        if cost < 0.400:
            return Text("Slow", style="red")
        return Text("Very Slow", style="bright_red")

    @staticmethod
    def show(test, data, evaluate_func):
        """
        +--------------+--------+--------+
        |  Screenshot  |  time  | Speed  |
        +--------------+--------+--------+
        |   nemu_ipc   | 0.019s |  Fast  |
        +--------------+--------+--------+
        """
        table = Table(show_lines=True)
        table.add_column(test, header_style="bright_cyan", style="cyan", no_wrap=True)
        table.add_column("Time", style="magenta")
        table.add_column("Speed", style="green")
        for row in data:
            table.add_row(
                row[0],
                float2str(row[1]),
                evaluate_func(row[1]),
            )
        logger.print(table, justify="center")

    def benchmark(self, screenshot: tuple[str] = (), click: tuple[str] = ()):
        logger.hr("Benchmark", level=1)
        logger.info(f"Testing screenshot methods: {screenshot}")
        logger.info(f"Testing click methods: {click}")

        screenshot_methods = {
            "nemu_ipc": self.device.screenshot_nemu_ipc,
        }
        click_methods = {
            "minitouch": self.device.click_minitouch,
        }

        screenshot_result = []
        for method in screenshot:
            result = self.benchmark_test(screenshot_methods[method])
            screenshot_result.append([method, result])

        area = (124, 4, 649, 106)  # Somewhere safe to click.
        click_result = []
        for method in click:
            x, y = random_rectangle_point(area)
            result = self.benchmark_test(click_methods[method], x, y)
            click_result.append([method, result])

        def compare(res):
            res = res[1]
            if not isinstance(res, (int, float)):
                return 100
            return res

        logger.hr("Benchmark Results", level=1)
        fastest_screenshot = "nemu_ipc"
        fastest_click = "minitouch"
        if screenshot_result:
            self.show(test="Screenshot", data=screenshot_result, evaluate_func=self.evaluate_screenshot)
            fastest = sorted(screenshot_result, key=compare)[0]
            logger.info(f"Recommend screenshot method: {fastest[0]} ({float2str(fastest[1])})")
            fastest_screenshot = fastest[0]
        if click_result:
            self.show(test="Control", data=click_result, evaluate_func=self.evaluate_click)
            fastest = sorted(click_result, key=compare)[0]
            logger.info(f"Recommend control method: {fastest[0]} ({float2str(fastest[1])})")
            fastest_click = fastest[0]

        return fastest_screenshot, fastest_click

    def get_test_methods(self) -> tuple[tuple[str], tuple[str]]:
        screenshot = ["nemu_ipc"] if self.device.nemu_ipc_available() else []
        click = ["minitouch"]

        scene = self.config.Benchmark_TestScene
        if "screenshot" not in scene:
            screenshot = []
        if "click" not in scene:
            click = []

        return tuple(screenshot), tuple(click)

    def run(self):
        self.config.override(Emulator_ScreenshotMethod="nemu_ipc", Emulator_ControlMethod="minitouch")
        self.ensure_campaign_ui("7-2", mode="normal")

        logger.attr("DeviceType", self.config.Benchmark_DeviceType)
        logger.attr("TestScene", self.config.Benchmark_TestScene)
        screenshot, click = self.get_test_methods()
        self.benchmark(screenshot, click)

    def run_simple_screenshot_benchmark(self):
        """
        Returns:
            str: The fastest screenshot method on current device.
        """
        if not self.device.nemu_ipc_available():
            logger.critical("当前个人版只保留 MuMu + nemu_ipc 截图方案")
            raise RequestHumanTakeover

        self.TEST_TOTAL = 3
        self.TEST_BEST = 1
        method, _ = self.benchmark(("nemu_ipc",), ())

        return method


def run_benchmark(config):
    try:
        Benchmark(config, task="Benchmark").run()
    except RequestHumanTakeover:
        logger.critical("Request human takeover")
        return False
    else:
        return True
