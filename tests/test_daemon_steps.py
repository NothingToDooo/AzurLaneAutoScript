from types import SimpleNamespace

from module.daemon.daemon import AzurLaneDaemon
from module.exception import CampaignEnd


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
        combat_status=lambda expected_end: None,
    )

    assert AzurLaneDaemon.handle_daemon_combat(daemon) is True


def test_handle_daemon_map_operation_sleeps_after_ambush_evade() -> None:
    sleep_calls = []
    daemon = SimpleNamespace(
        appear_then_click=lambda *args, **kwargs: True,
        device=SimpleNamespace(sleep=sleep_calls.append),
        handle_mystery_items=lambda: False,
    )

    assert AzurLaneDaemon.handle_daemon_map_operation(daemon) is True
    assert sleep_calls == [1]


def test_handle_daemon_map_preparation_skips_clicks_when_disabled() -> None:
    def unexpected_click():
        raise AssertionError("disabled map preparation should not click")

    daemon = SimpleNamespace(
        config=SimpleNamespace(Daemon_EnterMap=False),
        appear_then_click=unexpected_click,
    )

    assert AzurLaneDaemon.handle_daemon_map_preparation(daemon) is False
