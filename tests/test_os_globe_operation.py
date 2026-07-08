from module.os import assets as os_assets
from module.os.globe_operation import GlobeOperation


class _GlobeOperation(GlobeOperation):
    def __init__(self) -> None:
        self.has_switch = True
        self.pinned_name = ""
        self.selection_results: list[list[object]] = []
        self.executed_buttons: list[object] = []
        self.enter_count = 0
        self.update_pinned_on_execute = True

    def select_zone_type(self, types: tuple[str, ...] | list[str] | str = ("SAFE", "DANGEROUS")) -> bool:
        return self.zone_type_select(types)

    def zone_has_switch(self) -> bool:
        return self.has_switch

    def get_zone_pinned_name(self) -> str:
        return self.pinned_name

    def zone_select_enter(self) -> None:
        self.enter_count += 1

    def ensure_zone_select_expanded(self) -> list[object]:
        if self.selection_results:
            return self.selection_results.pop(0)
        return []

    def zone_select_execute(self, button: object) -> None:
        self.executed_buttons.append(button)
        if self.update_pinned_on_execute:
            self.pinned_name = self.pinned_to_name(button)


def test_zone_type_select_skips_zone_without_switch() -> None:
    operation = _GlobeOperation()
    operation.has_switch = False

    result = operation.select_zone_type("SAFE")

    assert result is True
    assert operation.enter_count == 0


def test_zone_type_select_keeps_matching_pinned_type() -> None:
    operation = _GlobeOperation()
    operation.pinned_name = "SAFE"

    result = operation.select_zone_type(("SAFE", "DANGEROUS"))

    assert result is True
    assert operation.executed_buttons == []


def test_zone_type_select_accepts_string_type() -> None:
    operation = _GlobeOperation()
    operation.selection_results = [[os_assets.SELECT_SAFE, os_assets.SELECT_DANGEROUS]]

    result = operation.select_zone_type("SAFE")

    assert result is True
    assert operation.executed_buttons == [os_assets.SELECT_SAFE]


def test_zone_type_select_falls_back_to_default_types() -> None:
    operation = _GlobeOperation()
    operation.selection_results = [[os_assets.SELECT_DANGEROUS, os_assets.SELECT_SAFE]]

    result = operation.select_zone_type(("ARCHIVE",))

    assert result is True
    assert operation.executed_buttons == [os_assets.SELECT_SAFE]


def test_zone_type_select_returns_false_after_retry_failure() -> None:
    operation = _GlobeOperation()
    operation.update_pinned_on_execute = False
    operation.selection_results = [
        [os_assets.SELECT_SAFE],
        [os_assets.SELECT_SAFE],
        [os_assets.SELECT_SAFE],
    ]

    result = operation.select_zone_type("SAFE")

    assert result is False
    assert operation.enter_count == 3
    assert operation.executed_buttons == [os_assets.SELECT_SAFE] * 3
