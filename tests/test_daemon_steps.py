from types import SimpleNamespace

from module.daemon.daemon import AzurLaneDaemon
from module.daemon.os_daemon import AzurLaneDaemon as OpsiDaemon
from module.daemon.os_daemon import ContinuousCombat
from module.exception import CampaignEnd


def _ignore_expected_end(expected_end) -> None:
    del expected_end


def test_handle_daemon_combat_prepares_and_finishes_battle_status() -> None:
    calls = []
    daemon = SimpleNamespace(
        is_combat_executing=lambda: False,
        combat_appear=lambda: True,
        combat_preparation=lambda: calls.append("preparation"),
        handle_battle_status=lambda: True,
        combat_status=lambda expected_end: calls.append(("combat_status", expected_end)),
    )

    assert AzurLaneDaemon.handle_daemon_combat(daemon) is True
    assert calls == ["preparation", ("combat_status", "no_searching")]


def test_handle_daemon_combat_treats_campaign_end_as_handled() -> None:
    def raise_campaign_end():
        raise CampaignEnd

    daemon = SimpleNamespace(
        is_combat_executing=lambda: False,
        combat_appear=lambda: False,
        combat_preparation=lambda: None,
        handle_battle_status=raise_campaign_end,
        combat_status=_ignore_expected_end,
    )

    assert AzurLaneDaemon.handle_daemon_combat(daemon) is True


def test_handle_daemon_map_operation_sleeps_after_ambush_evade() -> None:
    sleep_calls = []
    daemon = SimpleNamespace(
        appear_then_click=lambda *_args, **_kwargs: True,
        device=SimpleNamespace(sleep=sleep_calls.append),
        handle_mystery_items=lambda: False,
    )

    assert AzurLaneDaemon.handle_daemon_map_operation(daemon) is True
    assert sleep_calls == [1]


def test_handle_daemon_map_preparation_skips_clicks_when_disabled() -> None:
    def unexpected_click():
        message = "disabled map preparation should not click"
        raise AssertionError(message)

    daemon = SimpleNamespace(
        config=SimpleNamespace(Daemon_EnterMap=False),
        appear_then_click=unexpected_click,
    )

    assert AzurLaneDaemon.handle_daemon_map_preparation(daemon) is False


def test_handle_os_daemon_combat_treats_continuous_combat_as_handled() -> None:
    def raise_continuous_combat():
        raise ContinuousCombat

    daemon = SimpleNamespace(
        is_combat_executing=lambda: False,
        combat_appear=lambda: False,
        combat_preparation=lambda: None,
        handle_battle_status=raise_continuous_combat,
        combat_status=_ignore_expected_end,
    )

    assert OpsiDaemon.handle_os_daemon_combat(daemon) is True


def test_handle_os_daemon_map_event_clears_nearest_object_timer() -> None:
    calls = []
    daemon = SimpleNamespace(
        handle_map_event=lambda: True,
        _nearest_object_click_timer=SimpleNamespace(clear=lambda: calls.append("clear")),
    )

    assert OpsiDaemon.handle_os_daemon_map_event(daemon) is True
    assert calls == ["clear"]


def test_handle_os_daemon_port_repair_runs_repair_sequence() -> None:
    calls = []
    daemon = SimpleNamespace(
        config=SimpleNamespace(OpsiDaemon_RepairShip=True),
        appear=lambda *_args, **_kwargs: True,
        port_enter=lambda: calls.append("enter"),
        port_dock_repair=lambda: calls.append("repair"),
        port_quit=lambda: calls.append("quit"),
        interval_reset=lambda target: calls.append(("reset", target)),
    )

    assert OpsiDaemon.handle_os_daemon_port_repair(daemon) is True
    assert calls[:3] == ["enter", "repair", "quit"]
    assert calls[3][0] == "reset"
