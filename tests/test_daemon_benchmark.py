from types import SimpleNamespace

import pytest

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
def test_evaluate_screenshot(cost, expected: str) -> None:
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
def test_evaluate_click(cost, expected: str) -> None:
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
