from types import SimpleNamespace

import pytest

import module.daemon.benchmark as benchmark_module
from module.daemon.benchmark import Benchmark


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        ("Failed", "Failed"),
        (0.010, "Insane Fast"),
        (0.025, "Ultra Fast"),
        (0.100, "Very Fast"),
        (0.200, "Fast"),
        (0.300, "Medium"),
        (0.500, "Slow"),
        (0.750, "Very Slow"),
        (1.000, "Ultra Slow"),
    ],
)
def test_evaluate_screenshot(cost: str | float, expected: str) -> None:
    assert Benchmark.evaluate_screenshot(cost).plain == expected


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        ("Failed", "Failed"),
        (0.050, "Fast"),
        (0.100, "Medium"),
        (0.200, "Slow"),
        (0.400, "Very Slow"),
    ],
)
def test_evaluate_click(cost: str | float, expected: str) -> None:
    assert Benchmark.evaluate_click(cost).plain == expected


@pytest.mark.parametrize(
    ("scene", "expected"),
    [
        ("screenshot_click", (("nemu_ipc",), ("minitouch",))),
        ("screenshot", (("nemu_ipc",), ())),
        ("click", ((), ("minitouch",))),
    ],
)
def test_get_test_methods_uses_fixed_personal_stack(
    scene: str, expected: tuple[tuple[str, ...], tuple[str, ...]]
) -> None:
    benchmark = object.__new__(Benchmark)
    benchmark.config = SimpleNamespace(Benchmark_TestScene=scene)

    assert benchmark.get_test_methods() == expected


def test_benchmark_keeps_first_result_when_costs_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    class TieCost(float):
        pass

    first = TieCost(0.1)
    second = TieCost(0.1)
    costs = iter((first, second))
    benchmark = object.__new__(Benchmark)
    benchmark.device = SimpleNamespace(screenshot_nemu_ipc=lambda: None, click_minitouch=lambda *_: None)
    benchmark.benchmark_test = lambda _: next(costs)
    benchmark.show = lambda **_: None
    messages = []

    monkeypatch.setattr(benchmark_module.logger, "info", messages.append)
    monkeypatch.setattr(benchmark_module, "float2str", lambda value: "first" if value is first else "second")

    assert benchmark.benchmark(screenshot=("nemu_ipc", "nemu_ipc")) == ("nemu_ipc", "minitouch")
    assert "Fixed screenshot method: nemu_ipc (first)" in messages


def test_benchmark_restores_stuck_detection_after_measurement() -> None:
    events: list[str] = []

    class _DetectionScope:
        def __enter__(self) -> None:
            events.append("disable")

        def __exit__(self, *_args: object) -> None:
            events.append("enable")

    benchmark = object.__new__(Benchmark)
    benchmark.TEST_TOTAL = 1
    benchmark.TEST_BEST = 1
    benchmark.device = SimpleNamespace(suspend_stuck_detection=_DetectionScope)

    result = benchmark.benchmark_test(lambda: events.append("measure"))

    assert isinstance(result, float)
    assert events == ["disable", "measure", "enable"]
