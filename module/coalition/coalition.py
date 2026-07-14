from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from module.coalition.combat import CoalitionCombat
from module.coalition.profile import (
    CoalitionClientSession,
    CoalitionPtOcrProfile,
    CoalitionPtOcrStrategy,
)
from module.content.activity_profile import CoalitionStageId
from module.content.models import ContentId
from module.logger import logger
from module.ocr.ocr import Digit

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


class CoalitionPtOcr(Digit):
    __slots__ = ("_strategy",)

    def __init__(self, profile: CoalitionPtOcrProfile) -> None:
        self._strategy = profile.strategy
        if profile.alphabet is not None and profile.language is not None:
            super().__init__(
                profile.region,
                name="OCR_PT",
                letter=profile.letter,
                threshold=profile.threshold,
                alphabet=profile.alphabet,
                lang=profile.language,
            )
        elif profile.alphabet is not None:
            super().__init__(
                profile.region,
                name="OCR_PT",
                letter=profile.letter,
                threshold=profile.threshold,
                alphabet=profile.alphabet,
            )
        elif profile.language is not None:
            super().__init__(
                profile.region,
                name="OCR_PT",
                letter=profile.letter,
                threshold=profile.threshold,
                lang=profile.language,
            )
        else:
            super().__init__(
                profile.region,
                name="OCR_PT",
                letter=profile.letter,
                threshold=profile.threshold,
            )

    @override
    def after_process(self, result: str) -> int:
        logger.attr(self.name, result)
        if self._strategy is CoalitionPtOcrStrategy.AFTER_COLON:
            result = result.rsplit(":", maxsplit=1)[-1]
        elif self._strategy is CoalitionPtOcrStrategy.AFTER_X:
            result = result.rsplit("X", maxsplit=1)[-1]
        return super().after_process(result)


@dataclass(frozen=True, slots=True)
class CoalitionExecutionResult:
    content_id: ContentId
    stage_id: CoalitionStageId
    battle_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.content_id, ContentId):
            message = "content_id must be a ContentId"
            raise TypeError(message)
        if not isinstance(self.stage_id, CoalitionStageId):
            message = "stage_id must be a CoalitionStageId"
            raise TypeError(message)
        if type(self.battle_count) is not int or self.battle_count <= 0:
            message = "battle_count must be a positive integer"
            raise ValueError(message)


class Coalition(CoalitionCombat):
    def __init__(
        self,
        config: AzurLaneConfig | str,
        device: Device | str | None = None,
        *,
        client: CoalitionClientSession,
    ) -> None:
        if not isinstance(client, CoalitionClientSession):
            message = "client must be a CoalitionClientSession"
            raise TypeError(message)
        self.client = client
        super().__init__(config, device=device)

    def get_event_pt(self) -> int:
        ocr = CoalitionPtOcr(self.client.profile.pt_ocr)
        points = 0
        for _ in self.loop(timeout=1.5):
            points = ocr.ocr_single(self.device.image)
            # 999999 是客户端占位值，出现时继续等待真实数值。
            if points != 999999:
                break
        else:
            logger.warning("Wait PT timeout, assume current result")
        return points

    def coalition_execute_once(self) -> CoalitionExecutionResult:
        """执行一个已在构造边界验证完成的联合作战安全单元。"""
        content_id = self.client.activity.content_id
        stage = self.client.stage
        fleet = self.client.fleet
        self.config.apply_runtime_overlay(
            Campaign_Name=f"{content_id.value}_{stage.stage_id.value}",
            Campaign_UseAutoSearch=False,
            Coalition_Fleet=fleet.value,
            Fleet_FleetOrder="fleet1_all_fleet2_standby",
        )
        if fleet.value == "single" and self.config.Emotion_Fleet1Control == "prevent_red_face":
            logger.warning(
                "AL does not allow single coalition with emotion < 30, emotion control is forced to prevent_yellow_face"
            )
            self.config.apply_runtime_overlay(Emotion_Fleet1Control="prevent_yellow_face")

        self.enter_map()
        self.coalition_combat()
        return CoalitionExecutionResult(content_id, stage.stage_id, stage.battle_count)
