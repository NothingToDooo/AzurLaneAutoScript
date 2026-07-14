from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.logger import logger
from module.raid.assets import RAID_REWARDS
from module.raid.profile import (
    CounterOcrSpec,
    DigitOcrSpec,
    RaidAttemptSource,
    RaidRunPlan,
)
from module.raid.raid import Raid
from module.raid.result import RaidAttemptStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.base.type_alias import ImageArray


class RaidRun(Raid):
    @staticmethod
    def _remain_reader(spec: CounterOcrSpec | DigitOcrSpec) -> Callable[[ImageArray], int]:
        if isinstance(spec, DigitOcrSpec):
            return spec.create().ocr_single

        ocr = spec.create()

        def read(image: ImageArray) -> int:
            remaining, _, _ = ocr.ocr(image)
            return remaining

        return read

    def get_attempt_status(
        self,
        plan: RaidRunPlan,
        *,
        skip_first_screenshot: bool = True,
    ) -> RaidAttemptStatus:
        """稳定读取 plan 的剩余次数；unmetered profile 不执行 OCR。"""
        self._require_plan(plan)
        mode_profile = plan.mode_profile
        if mode_profile.attempt_source is RaidAttemptSource.UNMETERED:
            return RaidAttemptStatus(mode=plan.mode, source=RaidAttemptSource.UNMETERED, remaining=None)

        ocr_spec = mode_profile.remain_ocr
        if not isinstance(ocr_spec, CounterOcrSpec | DigitOcrSpec):
            message = f"metered raid mode {plan.mode.value!r} does not define remain OCR"
            raise TypeError(message)
        read_remaining = self._remain_reader(ocr_spec)

        confirm_timer = Timer(0.3, count=0)
        previous = 30
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            remaining = read_remaining(self.device.image)
            logger.attr(f"{plan.mode.value.capitalize()} Remain", remaining)

            if self.appear_then_click(RAID_REWARDS, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if remaining == previous:
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
            previous = remaining
        return RaidAttemptStatus(
            mode=plan.mode,
            source=RaidAttemptSource.METERED,
            remaining=remaining,
        )
