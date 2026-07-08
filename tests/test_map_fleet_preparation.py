from types import SimpleNamespace

from module.map import assets as map_assets
from module.map import map_fleet_preparation as fleet_preparation_module
from module.map.map_fleet_preparation import FleetPreparation


class _Device:
    def __init__(self) -> None:
        self.clicks = []
        self.screenshot_count = 0

    def click(self, button) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeFleetOperator:
    OFFSET = (0, 0)

    def __init__(self, assets, main) -> None:
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

    def is_hard_satisfied(self):
        self.main.calls.append((self.name, "is_hard_satisfied"))
        return self.hard_result

    def raise_hard_not_satisfied(self) -> None:
        self.main.calls.append((self.name, "raise_hard_not_satisfied"))

    def allow(self):
        self.main.calls.append((self.name, "allow"))
        if self.allow_results:
            return self.allow_results.pop(0)
        return False

    def clear(self) -> None:
        self.main.calls.append((self.name, "clear"))

    def ensure_to_be(self, index) -> None:
        self.main.calls.append((self.name, "ensure_to_be", index))


class _FleetPreparation(FleetPreparation):
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
            SUBMARINE=submarine_enabled,
        )
        self.device = _Device()
        self.map_fleet_checked = False
        self.map_is_hard_mode = False
        self.operator_configs = {}
        self.operators = {}
        self.calls = []

    def appear(self, _button, **_kwargs):
        return False


def test_fleet_preparation_skips_hard_mode_and_clears_unconfigured_submarine(monkeypatch) -> None:
    monkeypatch.setattr(fleet_preparation_module, "FleetOperator", _FakeFleetOperator)
    preparation = _FleetPreparation()
    preparation.operator_configs = {"submarine": {"hard": True, "allow": [True]}}

    assert preparation.fleet_preparation() is False

    assert preparation.map_is_hard_mode is True
    assert ("submarine", "clear") in preparation.calls


def test_fleet_preparation_sets_two_fleets_in_config_order(monkeypatch) -> None:
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
    assert preparation.config.SUBMARINE == 0


def test_fleet_preparation_fast_clears_submarine_when_not_configured(monkeypatch) -> None:
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
