from dataclasses import dataclass
from types import SimpleNamespace
from typing import override

import pytest

from module.os_handler.action_point import (
    ACTION_POINT_BOX,
    ActionPointHandler,
    ActionPointLimit,
    ActionPointZone,
    ActionPointZoneType,
)


@dataclass
class _Zone:
    hazard_level: int = 1
    is_port: bool = False


_ZONE = _Zone()


class _ActionPointContext(ActionPointHandler):
    config: SimpleNamespace

    def __init__(
        self,
        *,
        current: int,
        total: int,
        boxes: list[int],
        preserve: int = 0,
        buy_limit: int = 0,
    ) -> None:
        self._action_point_current = current
        self._action_point_total = total
        self._action_point_box = boxes
        self.config = SimpleNamespace(
            OS_ACTION_POINT_PRESERVE=preserve,
            OpsiGeneral_BuyActionPointLimit=buy_limit,
            OpsiGeneral_OilLimit=1000,
        )
        self.calls = []
        self.last_button: int | None = None

    @property
    def current_ap(self) -> int:
        return self._action_point_current

    @override
    def _is_in_action_point(self) -> bool:
        return True

    @override
    def action_point_safe_get(self) -> None:
        self.calls.append(("safe_get", None))

    def action_point_get_cost(self, zone: ActionPointZone, pinned: ActionPointZoneType) -> int:
        self.calls.append(("get_cost", zone, pinned))
        return 180

    @override
    def action_point_quit(self) -> None:
        self.calls.append(("quit", None))

    @override
    def action_point_buy(self, preserve: int = 1000) -> bool:
        self.calls.append(("buy", preserve))
        return False

    @override
    def action_point_set_button(self, index: int) -> bool:
        self.calls.append(("set_button", index))
        self.last_button = index
        return True

    @override
    def action_point_use(self) -> None:
        self.calls.append(("use", self.last_button))
        index = self.last_button
        assert index is not None
        self._action_point_box[index] -= 1
        self._action_point_current += ACTION_POINT_BOX[index]
        box_total = sum(amount * ACTION_POINT_BOX[index] for index, amount in enumerate(self._action_point_box))
        self._action_point_total = self._action_point_current + box_total


def test_handle_action_point_returns_true_when_current_ap_is_enough() -> None:
    context = _ActionPointContext(current=200, total=200, boxes=[0, 0, 0, 0])

    assert context.handle_action_point(zone=_ZONE, pinned="SAFE", cost=180) is True
    assert context.calls == [("safe_get", None), ("quit", None)]


def test_handle_action_point_uses_boxes_until_current_ap_is_enough() -> None:
    context = _ActionPointContext(current=150, total=220, boxes=[0, 1, 1, 0])

    assert context.handle_action_point(zone=_ZONE, pinned="SAFE", cost=180) is True
    assert ("set_button", 1) in context.calls
    assert ("set_button", 2) in context.calls
    assert context.current_ap == 220


def test_handle_action_point_raises_when_total_ap_is_not_enough() -> None:
    context = _ActionPointContext(current=50, total=70, boxes=[0, 1, 0, 0])

    with pytest.raises(ActionPointLimit):
        context.handle_action_point(zone=_ZONE, pinned="SAFE", cost=180)

    assert ("quit", None) in context.calls
