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


def _campaign_args_task(module_name: str, class_name: str) -> TaskSpec:
    return TaskSpec(module_name=module_name, class_name=class_name, args_factory=_campaign_args)


TASK_REGISTRY: dict[str, TaskSpec] = {
    # 普通任务：构造任务类后直接调用 run()。
    "research": _task("module.research.research", "RewardResearch"),
    "commission": _task("module.commission.commission", "RewardCommission"),
    "tactical": _task("module.tactical.tactical_class", "RewardTacticalClass"),
    "dorm": _task("module.dorm.dorm", "RewardDorm"),
    "meowfficer": _task("module.meowfficer.meowfficer", "RewardMeowfficer"),
    "guild": _task("module.guild.guild_reward", "RewardGuild"),
    "reward": _task("module.reward.reward", "Reward"),
    "awaken": _task("module.awaken.awaken", "Awaken"),
    "shipyard": _task("module.shipyard.shipyard_reward", "RewardShipyard"),
    "gacha": _task("module.gacha.gacha_reward", "RewardGacha"),
    "freebies": _task("module.freebies.freebies", "Freebies"),
    "minigame": _task("module.minigame.minigame", "Minigame"),
    "private_quarters": _task("module.private_quarters.private_quarters", "PrivateQuarters"),
    "daily": _task("module.daily.daily", "Daily"),
    "hard": _task("module.hard.hard", "CampaignHard"),
    "exercise": _task("module.exercise.exercise", "Exercise"),
    "sos": _task("module.sos.sos", "CampaignSos"),
    "raid_daily": _task("module.raid.daily", "RaidDaily"),
    "event_sp": _task("module.event.campaign_sp", "CampaignSP"),
    "maritime_escort": _task("module.event.maritime_escort", "MaritimeEscort"),
    "opsi_ash_assist": _task("module.os_ash.meta", "AshBeaconAssist"),
    "opsi_ash_beacon": _task("module.os_ash.meta", "OpsiAshBeacon"),
    "raid": _task("module.raid.run", "RaidRun"),
    "hospital": _task("module.event_hospital.hospital", "Hospital"),
    "coalition": _task("module.coalition.coalition", "Coalition"),
    "coalition_sp": _task("module.coalition.coalition_sp", "CoalitionSP"),
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
    "main": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "main2": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "main3": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "event": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "event2": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "c72_mystery_farming": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "c122_medium_leveling": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "c124_large_leveling": _campaign_args_task("module.campaign.run", "CampaignRun"),
    "war_archives": _campaign_args_task("module.war_archives.war_archives", "CampaignWarArchives"),
    "gems_farming": _campaign_args_task("module.campaign.gems_farming", "GemsFarming"),
}


def get_task_spec(command: str) -> TaskSpec | None:
    return TASK_REGISTRY.get(command)
