import re
from collections.abc import Sequence
from typing import cast, overload

from module.base.filter import Filter
from module.campaign.run import CampaignRun


class EventStage:
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.stage = "unknown"
        if filename[-3:] == ".py":
            self.stage = filename[:-3]

    def __str__(self) -> str:
        return self.stage

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    __hash__ = None


STAGE_FILTER = Filter[EventStage](regex=re.compile(r"^(.*?)$"), attr=("stage",))


class EventBase(CampaignRun):
    def load_campaign(self, name: str, folder: str = "campaign_main") -> bool:
        loaded = super().load_campaign(name, folder=folder)
        self.campaign.config.temporary(MAP_IS_ONE_TIME_STAGE=False)
        return loaded

    @overload
    def convert_stages(self, stages: str) -> str: ...

    @overload
    def convert_stages(self, stages: Sequence[str]) -> list[str]: ...

    @overload
    def convert_stages(self, stages: Sequence[EventStage]) -> list[EventStage]: ...

    @overload
    def convert_stages(self, stages: Filter[EventStage]) -> Filter[EventStage]: ...

    def convert_stages(
        self, stages: str | Sequence[str | EventStage] | Filter[EventStage]
    ) -> str | list[str] | list[EventStage] | Filter[EventStage]:
        """将字符串、列表或筛选器中的关卡名统一转换为当前活动的规范名称。"""

        def convert(n: str) -> str:
            return self.handle_stage_name(n, folder=self.config.Campaign_Event)[0]

        if isinstance(stages, str):
            return convert(stages)
        if isinstance(stages, Sequence):
            out: list[str | EventStage] = []
            for name in stages:
                if isinstance(name, str):
                    out.append(convert(name))
                else:
                    event_stage = cast("EventStage", name)
                    event_stage.stage = convert(event_stage.stage)
                    out.append(event_stage)
            return cast("list[str] | list[EventStage]", out)
        if isinstance(stages, Filter):
            stages.filter = [[convert(cast("str", selection[0]))] for selection in stages.filter]
            return stages
        return stages
