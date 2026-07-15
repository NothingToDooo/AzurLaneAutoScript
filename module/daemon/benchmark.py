import time
from typing import TYPE_CHECKING

import numpy as np
from rich.table import Table
from rich.text import Text

from module.base.utils import float2str as float2str_
from module.base.utils import random_rectangle_point
from module.campaign.campaign_ui import CampaignUI
from module.exception import RequestHumanTakeover
from module.logger import emit_renderables, logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

type BenchmarkResult = float | str
type BenchmarkRecord = tuple[str, BenchmarkResult]
type SpeedLevel = tuple[float, str, str]


def float2str(n: float | str, decimal: int = 3) -> str:
    if not isinstance(n, (float, int)):
        return str(n)
    return float2str_(n, decimal=decimal) + "s"


_SCREENSHOT_SPEED_LEVELS = (
    (0.025, "Insane Fast", "bold bright_green"),
    (0.100, "Ultra Fast", "bold bright_green"),
    (0.200, "Very Fast", "bright_green"),
    (0.300, "Fast", "green"),
    (0.500, "Medium", "yellow"),
    (0.750, "Slow", "red"),
    (1.000, "Very Slow", "bright_red"),
)
_CLICK_SPEED_LEVELS = (
    (0.100, "Fast", "bright_green"),
    (0.200, "Medium", "yellow"),
    (0.400, "Slow", "red"),
)


def _evaluate_speed(
    cost: float | str,
    levels: Sequence[SpeedLevel],
    fallback: tuple[str, str],
) -> Text:
    if not isinstance(cost, (float, int)):
        return Text(cost, style="bold bright_red")

    for limit, label, style in levels:
        if cost < limit:
            return Text(label, style=style)
    label, style = fallback
    return Text(label, style=style)


class Benchmark(CampaignUI):
    TEST_TOTAL = 15
    TEST_BEST = int(TEST_TOTAL * 0.8)

    def benchmark_test[R, **P](self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> BenchmarkResult:
        logger.hr("Benchmark test", level=2)
        function_name = getattr(func, "__name__", type(func).__name__)
        logger.info(f"Testing function: {function_name}")
        record = []

        with self.device.suspend_stuck_detection():
            for n in range(1, self.TEST_TOTAL + 1):
                start = time.perf_counter()

                try:
                    func(*args, **kwargs)
                except RequestHumanTakeover:
                    logger.critical("RequestHumanTakeover")
                    logger.warning(f"Benchmark tests failed on func: {function_name}")
                    return "Failed"

                cost = time.perf_counter() - start
                logger.attr(f"{str(n).rjust(2, '0')}/{self.TEST_TOTAL}", f"{float2str(cost)}")
                record.append(cost)

        logger.info("Benchmark tests done")
        average = float(np.mean(np.sort(record)[: self.TEST_BEST]))
        logger.info(f"Time cost {float2str(average)} ({self.TEST_BEST} best results out of {self.TEST_TOTAL} tests)")
        return average

    @staticmethod
    def evaluate_screenshot(cost: float | str) -> Text:
        return _evaluate_speed(cost, _SCREENSHOT_SPEED_LEVELS, ("Ultra Slow", "bold bright_red"))

    @staticmethod
    def evaluate_click(cost: float | str) -> Text:
        return _evaluate_speed(cost, _CLICK_SPEED_LEVELS, ("Very Slow", "bright_red"))

    @staticmethod
    def show(
        test: str,
        data: Sequence[BenchmarkRecord],
        evaluate_func: Callable[[BenchmarkResult], Text],
    ) -> None:
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
        emit_renderables(table, justify="center")

    def benchmark(self, screenshot: tuple[str, ...] = (), click: tuple[str, ...] = ()) -> tuple[str, str]:
        logger.hr("Benchmark", level=1)
        logger.info(f"Testing screenshot methods: {screenshot}")
        logger.info(f"Testing click methods: {click}")

        screenshot_methods = {
            "nemu_ipc": self.device.screenshot_nemu_ipc,
        }
        click_methods = {
            "minitouch": self.device.click_minitouch,
        }

        screenshot_result: list[BenchmarkRecord] = []
        for method in screenshot:
            result = self.benchmark_test(screenshot_methods[method])
            screenshot_result.append((method, result))

        area = (124, 4, 649, 106)  # 避开危险操作的点击区域。
        click_result: list[BenchmarkRecord] = []
        for method in click:
            x, y = random_rectangle_point(area)
            result = self.benchmark_test(click_methods[method], x, y)
            click_result.append((method, result))

        def compare(result: BenchmarkRecord) -> float:
            cost = result[1]
            if not isinstance(cost, int | float):
                return 100
            return float(cost)

        logger.hr("Benchmark Results", level=1)
        fastest_screenshot = "nemu_ipc"
        fastest_click = "minitouch"
        if screenshot_result:
            self.show(test="Screenshot", data=screenshot_result, evaluate_func=self.evaluate_screenshot)
            fastest = min(screenshot_result, key=compare)
            logger.info(f"Fixed screenshot method: {fastest[0]} ({float2str(fastest[1])})")
            fastest_screenshot = fastest[0]
        if click_result:
            self.show(test="Control", data=click_result, evaluate_func=self.evaluate_click)
            fastest = min(click_result, key=compare)
            logger.info(f"Fixed control method: {fastest[0]} ({float2str(fastest[1])})")
            fastest_click = fastest[0]

        return fastest_screenshot, fastest_click

    def get_test_methods(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        screenshot = ["nemu_ipc"]
        click = ["minitouch"]

        scene = self.config.Benchmark_TestScene
        if "screenshot" not in scene:
            screenshot = []
        if "click" not in scene:
            click = []

        return tuple(screenshot), tuple(click)

    def run(self) -> None:
        self.ensure_campaign_ui("7-2", mode="normal")

        logger.attr("TestScene", self.config.Benchmark_TestScene)
        screenshot, click = self.get_test_methods()
        self.benchmark(screenshot, click)
