from types import SimpleNamespace
from typing import TYPE_CHECKING, TypedDict, cast, override

import numpy as np
import pytest

from module.exception import HardNotSatisfied, RequestHumanTakeover
from module.map import assets as map_assets
from module.map import map_fleet_preparation as fleet_preparation_module
from module.map.map_fleet_preparation import FleetOperator, FleetOperatorAssets, FleetPreparation

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.base.type_alias import ImageArray
    from module.handler.info_handler import InfoHandler


class _OperatorConfig(TypedDict, total=False):
    hard: bool
    allow: list[bool]


type _Call = tuple[str, str] | tuple[str, str, int]


class _Device:
    def __init__(self) -> None:
        self.clicks: list[Button] = []
        self.screenshot_count = 0

    def click(self, button: Button) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeFleetOperator:
    OFFSET = (0, 0)

    def __init__(self, assets: FleetOperatorAssets, main: _FleetPreparation) -> None:
        self.main = main
        self.clear_button = assets.clear
        self.name = {
            map_assets.FLEET_1_CHOOSE: "fleet1",
            map_assets.FLEET_2_CHOOSE: "fleet2",
            map_assets.SUBMARINE_CHOOSE: "submarine",
        }[assets.choose]
        config = main.operator_configs.get(self.name, {})
        self.hard_result = config.get("hard", False)
        self.allow_results = list(config.get("allow", []))
        self.main.operators[self.name] = self

    def is_hard_satisfied(self) -> bool:
        self.main.calls.append((self.name, "is_hard_satisfied"))
        return self.hard_result

    def raise_hard_not_satisfied(self) -> None:
        self.main.calls.append((self.name, "raise_hard_not_satisfied"))

    def allow(self) -> bool:
        self.main.calls.append((self.name, "allow"))
        if self.allow_results:
            return self.allow_results.pop(0)
        return False

    def clear(self) -> None:
        self.main.calls.append((self.name, "clear"))

    def ensure_to_be(self, index: int) -> None:
        self.main.calls.append((self.name, "ensure_to_be", index))


class _FleetPreparation(FleetPreparation):
    config: SimpleNamespace
    device: _Device

    def __init__(
        self,
        *,
        fleet1: int = 1,
        fleet2: int = 0,
        submarine: int = 0,
        submarine_enabled: int = 1,
    ) -> None:
        self.config = SimpleNamespace(
            Fleet_Fleet1=fleet1,
            Fleet_Fleet2=fleet2,
            Submarine_Fleet=submarine,
            submarine=submarine_enabled,
        )
        self.device = _Device()
        self.map_fleet_checked = False
        self.map_is_hard_mode = False
        self.operator_configs: dict[str, _OperatorConfig] = {}
        self.operators: dict[str, _FakeFleetOperator] = {}
        self.calls: list[_Call] = []
        self.appear_calls: list[Button] = []

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, interval, similarity, threshold
        self.appear_calls.append(button)
        return False


def _fleet_operator_in_use(image: ImageArray) -> bool:
    def image_crop(_area: object, *, copy: bool) -> ImageArray:
        del copy
        return image

    main = cast(
        "InfoHandler",
        SimpleNamespace(
            appear=lambda _button, **_kwargs: False,
            image_crop=image_crop,
        ),
    )
    operator = FleetOperator(
        FleetOperatorAssets(
            choose=map_assets.FLEET_1_CHOOSE,
            advice=map_assets.FLEET_1_ADVICE,
            bar=map_assets.FLEET_1_BAR,
            clear=map_assets.FLEET_1_CLEAR,
            in_use=map_assets.FLEET_1_IN_USE,
            hard_satisfied=map_assets.FLEET_1_HARD_SATIESFIED,
        ),
        main,
    )
    return operator.in_use()


def test_fleet_preparation_skips_hard_mode_and_clears_unconfigured_submarine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fleet_preparation_module, "FleetOperator", _FakeFleetOperator)
    preparation = _FleetPreparation()
    preparation.operator_configs = {"submarine": {"hard": True, "allow": [True]}}

    assert preparation.fleet_preparation() is False

    assert preparation.map_is_hard_mode is True
    assert ("submarine", "clear") in preparation.calls


def test_fleet_preparation_sets_two_fleets_in_config_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fleet_preparation_module, "FleetOperator", _FakeFleetOperator)
    preparation = _FleetPreparation(fleet1=1, fleet2=2)
    preparation.operator_configs = {"submarine": {"allow": [False]}}

    assert preparation.fleet_preparation() is True

    assert preparation.calls[-4:] == [
        ("submarine", "allow"),
        ("fleet2", "clear"),
        ("fleet1", "ensure_to_be", 1),
        ("fleet2", "ensure_to_be", 2),
    ]
    assert preparation.config.submarine == 0


def test_fleet_preparation_fast_clears_submarine_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fleet_preparation_module, "FleetOperator", _FakeFleetOperator)
    preparation = _FleetPreparation(fleet1=1, fleet2=0, submarine=0)
    preparation.operator_configs = {
        "fleet2": {"allow": [True, False]},
        "submarine": {"allow": [True, True]},
    }

    assert preparation.fleet_preparation() is True

    assert preparation.device.clicks == [
        map_assets.FLEET_2_CLEAR,
        map_assets.SUBMARINE_CLEAR,
    ]
    assert preparation.device.screenshot_count == 1
    assert ("submarine", "clear") in preparation.calls


def test_hard_not_satisfied_remains_a_human_takeover_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    operator = object.__new__(FleetOperator)
    operator.main = SimpleNamespace(config=SimpleNamespace(Campaign_Name="3-4"))
    monkeypatch.setattr(operator, "is_hard_satisfied", lambda: False)
    monkeypatch.setattr(FleetOperator, "__str__", lambda _self: "fleet1")

    with pytest.raises(HardNotSatisfied) as exc_info:
        operator.raise_hard_not_satisfied()

    assert isinstance(exc_info.value, RequestHumanTakeover)


@pytest.mark.parametrize(
    ("color", "expected"),
    [
        pytest.param((224, 154, 114), True, id="perseus-skin"),
        pytest.param((124, 141, 171), True, id="akane-shinjo-skin"),
        pytest.param((71, 70, 63), False, id="empty-fleet"),
    ],
)
def test_fleet_operator_in_use_handles_flat_skin_colors(
    color: tuple[int, int, int],
    *,
    expected: bool,
) -> None:
    image = np.full((32, 32, 3), color, dtype=np.uint8)

    assert _fleet_operator_in_use(image) is expected


def test_fleet_operator_in_use_keeps_high_variance_detection() -> None:
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    image[:, ::2] = 255

    assert _fleet_operator_in_use(image) is True
