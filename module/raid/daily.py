import re

from module.base.filter import Filter
from module.logger import logger
from module.raid.run import RaidRun
from module.reward.reward import Reward
from module.ui.page import page_raid


class RaidStage:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


STAGES = ["easy", "normal", "hard"]
STAGE_FILTER = Filter(regex=re.compile(r"(\w+)"), attr=["name"])


class RaidDaily(RaidRun):
    def run(self, name="", mode="", total=0):
        """按筛选完成每日 easy、normal、hard；配置含 ex 时领取任务票后最后执行。

        name 为空时读取当前活动；RPG 共斗没有每日任务，会直接禁用调度。
        """
        _ = (mode, total)
        if self.is_raid_rpg():
            logger.info("RPG raid has no dailies")
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        name = name or self.config.Campaign_Event
        stages = [RaidStage(name) for name in STAGES]
        STAGE_FILTER.load(self.config.RaidDaily_StageFilter)
        stages = STAGE_FILTER.apply(stages)

        self.ui_ensure(page_raid)

        for stage in stages:
            mode = stage.name
            logger.hr(mode, level=1)
            for _ in range(15):
                remain = self.get_remain(mode=mode)
                if remain <= 0:
                    break
                super().run(name=name, mode=mode, total=1)

        stages = [stage.lower().strip() for stage in self.config.RaidDaily_StageFilter.split(">")]
        if "ex" in stages:
            # EX 票来自任意难度累计清理 5 次和 10 次的任务奖励。
            self.ui_goto_main()
            Reward(self.config, self.device).reward_mission(daily=self.config.Reward_CollectMission, weekly=False)
            self.ui_ensure(page_raid)

            logger.hr("ex", level=1)
            super().run(name=name, mode="ex", total=self.get_remain("ex"))

        self.config.task_delay(server_update=True)
