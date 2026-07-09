from module.map import assets as map_assets
from module.map.map_operation import MapOperation


class _Config:
    MAP_HAS_MODE_SWITCH = True
    MAP_HAS_CLEAR_PERCENTAGE = True
    MAP_IS_ONE_TIME_STAGE = False


class _Device:
    def __init__(self, calls):
        self.calls = calls

    def click(self, button):
        self.calls.append(("click", button.name))


class _Timer:
    def __init__(self, reached=False):
        self.is_reached = reached
        self.reset_count = 0

    def reached(self):
        return self.is_reached

    def reset(self):
        self.reset_count += 1


class _MapOperation(MapOperation):
    config: _Config
    device: _Device
    map_clear_percentage_prev: float
    map_clear_percentage: float
    map_clear_percentage_timer: _Timer

    def __init__(self):
        self.calls = []
        self.config = _Config()
        self.device = _Device(self.calls)
        self.normal_switch_visible = False
        self.hard_switch_visible = False
        self.hard_switch_active = False
        self.map_preparation_visible = False
        self.info_bar_visible = False
        self.map_clear_percentage_prev = -1
        self.map_clear_percentage = 0
        self.map_clear_percentage_timer = _Timer()

    def match_template_color(self, button, offset=(0, 0), interval=0):
        self.calls.append(("match_template_color", button.name, offset, interval))
        return self.normal_switch_visible

    def _is_mod_switch_hard_appear(self, active=True, interval=0):
        self.calls.append(("hard_switch_appear", active, interval))
        if active:
            return self.hard_switch_active
        return self.hard_switch_visible

    def interval_reset(self, button):
        self.calls.append(("interval_reset", button.name))

    def appear(self, button, offset=(0, 0)):
        self.calls.append(("appear", button.name, offset))
        return self.map_preparation_visible

    def info_bar_count(self):
        self.calls.append(("info_bar_count",))
        return self.info_bar_visible

    def get_map_clear_percentage(self):
        self.calls.append(("get_map_clear_percentage",))
        return self.map_clear_percentage


def test_handle_map_mode_switch_normal_clicks_when_hard_visible() -> None:
    operation = _MapOperation()
    operation.hard_switch_visible = True

    assert operation.handle_map_mode_switch("normal") is False

    assert ("click", map_assets.MAP_MODE_SWITCH_NORMAL.name) in operation.calls
    assert ("interval_reset", map_assets.MAP_MODE_SWITCH_HARD.name) in operation.calls


def test_handle_map_mode_switch_hard_is_satisfied_when_active() -> None:
    operation = _MapOperation()
    operation.hard_switch_active = True

    assert operation.handle_map_mode_switch("hard") is True

    assert operation.calls == [("hard_switch_appear", True, 0)]


def test_handle_map_preparation_resets_percentage_when_button_absent() -> None:
    operation = _MapOperation()
    operation.map_clear_percentage_prev = 0.5
    timer = _Timer()
    operation.map_clear_percentage_timer = timer

    assert operation.handle_map_preparation() is False

    assert operation.map_clear_percentage_prev == -1
    assert timer.reset_count == 1


def test_handle_map_preparation_returns_true_without_percentage() -> None:
    operation = _MapOperation()
    operation.map_preparation_visible = True
    operation.config.MAP_HAS_CLEAR_PERCENTAGE = False

    assert operation.handle_map_preparation() is True


def test_handle_map_preparation_waits_for_stable_percentage() -> None:
    operation = _MapOperation()
    operation.map_preparation_visible = True
    operation.map_clear_percentage_prev = 0.4
    operation.map_clear_percentage = 0.41
    operation.map_clear_percentage_timer = _Timer(reached=True)

    assert operation.handle_map_preparation() is True
    assert operation.map_clear_percentage_prev == 0.41


def test_handle_map_preparation_accepts_final_percentage_jump() -> None:
    operation = _MapOperation()
    operation.map_preparation_visible = True
    operation.map_clear_percentage_prev = 0.6
    operation.map_clear_percentage = 0.99

    assert operation.handle_map_preparation() is True
