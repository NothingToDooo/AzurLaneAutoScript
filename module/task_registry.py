from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any

type TaskArgsFactory = Callable[[Any], tuple[tuple[Any, ...], dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    module_name: str
    class_name: str
    method_name: str = "run"
    args_factory: TaskArgsFactory | None = None

    def execute(self, runner: Any) -> None:
        module = import_module(self.module_name)
        task_class = getattr(module, self.class_name)
        task = task_class(config=runner.config, device=runner.device)
        args, kwargs = self.args_factory(runner) if self.args_factory is not None else ((), {})
        getattr(task, self.method_name)(*args, **kwargs)


def _campaign_args(runner: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:
    config = runner.config
    return (
        (),
        {
            "name": config.Campaign_Name,
            "folder": config.Campaign_Event,
            "mode": config.Campaign_Mode,
        },
    )


def _task(module_name: str, class_name: str, method_name: str = "run") -> TaskSpec:
    return TaskSpec(module_name=module_name, class_name=class_name, method_name=method_name)


def _campaign_task() -> TaskSpec:
    return TaskSpec(module_name="module.campaign.run", class_name="CampaignRun", args_factory=_campaign_args)


TASK_REGISTRY: dict[str, TaskSpec] = {
    # 商店任务共用 RewardShop，只切换执行方法。
    "shop_frequent": _task("module.shop.shop_reward", "RewardShop", "run_frequent"),
    "shop_once": _task("module.shop.shop_reward", "RewardShop", "run_once"),
    # 活动 ABCD 入口共用同一个任务类，具体章节由配置决定。
    "event_a": _task("module.event.campaign_abcd", "CampaignABCD"),
    "event_b": _task("module.event.campaign_abcd", "CampaignABCD"),
    "event_c": _task("module.event.campaign_abcd", "CampaignABCD"),
    "event_d": _task("module.event.campaign_abcd", "CampaignABCD"),
    # 大世界任务已经集中在 OSCampaignRun，注册表只负责分发到对应方法。
    "opsi_explore": _task("module.campaign.os_run", "OSCampaignRun", "opsi_explore"),
    "opsi_shop": _task("module.campaign.os_run", "OSCampaignRun", "opsi_shop"),
    "opsi_voucher": _task("module.campaign.os_run", "OSCampaignRun", "opsi_voucher"),
    "opsi_daily": _task("module.campaign.os_run", "OSCampaignRun", "opsi_daily"),
    "opsi_obscure": _task("module.campaign.os_run", "OSCampaignRun", "opsi_obscure"),
    "opsi_month_boss": _task("module.campaign.os_run", "OSCampaignRun", "opsi_month_boss"),
    "opsi_abyssal": _task("module.campaign.os_run", "OSCampaignRun", "opsi_abyssal"),
    "opsi_archive": _task("module.campaign.os_run", "OSCampaignRun", "opsi_archive"),
    "opsi_stronghold": _task("module.campaign.os_run", "OSCampaignRun", "opsi_stronghold"),
    "opsi_meowfficer_farming": _task("module.campaign.os_run", "OSCampaignRun", "opsi_meowfficer_farming"),
    "opsi_hazard1_leveling": _task("module.campaign.os_run", "OSCampaignRun", "opsi_hazard1_leveling"),
    "opsi_cross_month": _task("module.campaign.os_run", "OSCampaignRun", "opsi_cross_month"),
    # 这些入口都是 CampaignRun，只在运行时读取当前战役配置。
    "main": _campaign_task(),
    "main2": _campaign_task(),
    "main3": _campaign_task(),
    "event": _campaign_task(),
    "event2": _campaign_task(),
    "c72_mystery_farming": _campaign_task(),
    "c122_medium_leveling": _campaign_task(),
    "c124_large_leveling": _campaign_task(),
}


def get_task_spec(command: str) -> TaskSpec | None:
    return TASK_REGISTRY.get(command)
