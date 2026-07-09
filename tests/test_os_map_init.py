from module.os.map import OSMap
from module.ui.page import page_os


class _Task:
    command = "OpsiAshBeacon"


class _Config:
    def __init__(self) -> None:
        self.task = _Task()
        self.bound = ["Legacy_dL", "Legacy_tZ"]
        self.Legacy_dL = 2
        self.Legacy_tZ = 22
        self.override_calls: list[dict[str, object]] = []

    def override(self, **kwargs: object) -> None:
        self.override_calls.append(kwargs)


class _Zone:
    def __init__(self, zone_id: int) -> None:
        self.zone_id = zone_id


class _Map(OSMap):
    config: _Config
    zone: _Zone

    def __init__(
        self,
        *,
        zone_id: int = 1,
        in_map: bool = True,
        in_globe: bool = False,
        os_page_visible: bool = False,
        special_zone: bool = False,
    ) -> None:
        self.config = _Config()
        self.zone = _Zone(zone_id)
        self.in_map = in_map
        self.in_globe = in_globe
        self.os_page_visible = os_page_visible
        self.special_zone = special_zone
        self.calls: list[tuple[object, ...]] = []

    def name_to_zone(self, value: object) -> object:
        message = f"legacy zone override should not run: {value}"
        raise AssertionError(message)

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self.in_map

    def is_in_globe(self) -> bool:
        self.calls.append(("is_in_globe",))
        return self.in_globe

    def os_globe_goto_map(self) -> None:
        self.calls.append(("os_globe_goto_map",))

    def ui_page_appear(self, page: object) -> bool:
        self.calls.append(("ui_page_appear", page))
        return self.os_page_visible

    def ui_goto_main(self) -> None:
        self.calls.append(("ui_goto_main",))

    def ui_ensure(self, page: object) -> None:
        self.calls.append(("ui_ensure", page))

    def zone_init(self) -> None:
        self.calls.append(("zone_init",))

    def hp_reset(self) -> None:
        self.calls.append(("hp_reset",))

    def handle_after_auto_search(self) -> bool:
        self.calls.append(("handle_after_auto_search",))
        return False

    def handle_current_fleet_resolve(self, *, revert: bool = False) -> bool:
        self.calls.append(("handle_current_fleet_resolve", revert))
        return False

    def is_in_special_zone(self) -> bool:
        self.calls.append(("is_in_special_zone",))
        return self.special_zone

    def map_exit(self) -> None:
        self.calls.append(("map_exit",))

    def handle_ash_beacon_attack(self) -> None:
        self.calls.append(("handle_ash_beacon_attack",))

    def run_auto_search(self, **kwargs: object) -> None:
        self.calls.append(("run_auto_search", kwargs))


def test_os_init_applies_personal_defaults_without_legacy_bound_overrides() -> None:
    runner = _Map()
    runner.config.task.command = "iM"

    runner.os_init()

    assert runner.config.override_calls == [
        {"Submarine_Fleet": 1, "Submarine_Mode": "every_combat", "STORY_ALLOW_SKIP": False}
    ]


def test_os_init_moves_from_globe_to_map() -> None:
    runner = _Map(in_map=False, in_globe=True)

    runner.os_init()

    assert ("os_globe_goto_map",) in runner.calls
    assert ("ui_ensure", page_os) not in runner.calls


def test_os_init_returns_from_os_page_before_ensuring_page() -> None:
    runner = _Map(in_map=False, os_page_visible=True)

    runner.os_init()

    assert runner.calls[:5] == [
        ("is_in_map",),
        ("is_in_globe",),
        ("ui_page_appear", page_os),
        ("ui_goto_main",),
        ("ui_ensure", page_os),
    ]


def test_os_init_exits_special_zone_before_current_zone_clear() -> None:
    runner = _Map(special_zone=True)

    runner.os_init()

    assert runner.calls.index(("map_exit",)) < runner.calls.index(("run_auto_search", {"rescan": False}))


def test_os_init_skips_first_auto_search_in_ash_beacon_zones() -> None:
    runner = _Map(zone_id=44)

    runner.os_init()

    assert ("handle_ash_beacon_attack",) in runner.calls
    assert ("run_auto_search", {"rescan": False}) not in runner.calls
