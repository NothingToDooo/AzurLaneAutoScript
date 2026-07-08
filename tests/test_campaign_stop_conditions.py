from types import SimpleNamespace

from module.campaign.run import CampaignRun


class _StopConfig:
    def __init__(self) -> None:
        self.StopCondition_RunCount = 1
        self.StopCondition_ReachLevel = 0
        self.StopCondition_OilLimit = 0
        self.StopCondition_GetNewShip = False
        self.TaskBalancer_Enable = False
        self.Scheduler_Enable = True
        self.delays: list[dict[str, object]] = []

    def task_delay(self, **kwargs: object) -> None:
        self.delays.append(kwargs)


class _StopCampaign:
    def __init__(self) -> None:
        self.config = SimpleNamespace(LV_TRIGGERED=False, GET_SHIP_TRIGGERED=False)
        self.auto_search_oil_limit_triggered = False
        self.auto_search_coin_limit_triggered = False
        self.event_pt_triggered = False
        self.event_pt_checks = 0

    def event_pt_limit_triggered(self) -> bool:
        self.event_pt_checks += 1
        return self.event_pt_triggered


def _make_runner(*, oil: int = 1000, task_balancer_triggered: bool = False):
    runner = object.__new__(CampaignRun)
    runner.config = _StopConfig()
    runner.campaign = _StopCampaign()
    runner.run_limit = 0
    runner.run_count = 0
    runner.task_balancer_calls = 0

    def get_oil() -> int:
        return oil

    def triggered_task_balancer() -> bool:
        return task_balancer_triggered

    def handle_task_balancer() -> None:
        runner.task_balancer_calls += 1

    runner.get_oil = get_oil
    runner.triggered_task_balancer = triggered_task_balancer
    runner.handle_task_balancer = handle_task_balancer
    return runner


def test_run_count_limit_disables_scheduler() -> None:
    runner = _make_runner()
    runner.run_limit = 1
    runner.config.StopCondition_RunCount = 0

    assert runner.triggered_stop_condition()
    assert runner.config.StopCondition_RunCount == 0
    assert not runner.config.Scheduler_Enable


def test_reach_level_limit_disables_scheduler() -> None:
    runner = _make_runner()
    runner.config.StopCondition_ReachLevel = 120
    runner.campaign.config.LV_TRIGGERED = True

    assert runner.triggered_stop_condition()
    assert not runner.config.Scheduler_Enable


def test_oil_limit_delays_current_task() -> None:
    runner = _make_runner(oil=499)

    assert runner.triggered_stop_condition(oil_check=True)
    assert runner.config.delays == [{"minute": (120, 240)}]


def test_oil_limit_can_be_skipped() -> None:
    runner = _make_runner(oil=499)

    assert not runner.triggered_stop_condition(oil_check=False)
    assert runner.config.delays == []


def test_auto_search_oil_limit_delays_current_task() -> None:
    runner = _make_runner()
    runner.campaign.auto_search_oil_limit_triggered = True

    assert runner.triggered_stop_condition()
    assert runner.config.delays == [{"minute": (120, 240)}]


def test_get_new_ship_limit_disables_scheduler() -> None:
    runner = _make_runner()
    runner.config.StopCondition_GetNewShip = True
    runner.campaign.config.GET_SHIP_TRIGGERED = True

    assert runner.triggered_stop_condition()
    assert not runner.config.Scheduler_Enable


def test_event_pt_limit_can_be_skipped_with_oil_check() -> None:
    runner = _make_runner()
    runner.campaign.event_pt_triggered = True

    assert not runner.triggered_stop_condition(oil_check=False)
    assert runner.campaign.event_pt_checks == 0


def test_event_pt_limit_uses_campaign_check() -> None:
    runner = _make_runner()
    runner.campaign.event_pt_triggered = True

    assert runner.triggered_stop_condition(oil_check=True)
    assert runner.campaign.event_pt_checks == 1


def test_auto_search_coin_limit_calls_task_balancer() -> None:
    runner = _make_runner()
    runner.config.TaskBalancer_Enable = True
    runner.campaign.auto_search_coin_limit_triggered = True

    assert runner.triggered_stop_condition()
    assert runner.task_balancer_calls == 1


def test_task_balancer_limit_calls_task_balancer() -> None:
    runner = _make_runner(task_balancer_triggered=True)
    runner.config.TaskBalancer_Enable = True
    runner.run_count = 1

    assert runner.triggered_stop_condition(oil_check=True)
    assert runner.task_balancer_calls == 1


def test_triggered_stop_condition_short_circuits_in_order() -> None:
    runner = _make_runner(oil=499)
    runner.run_limit = 1
    runner.config.StopCondition_RunCount = 0

    assert runner.triggered_stop_condition()
    assert runner.config.delays == []
