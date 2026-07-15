import re
from datetime import timedelta
from typing import Unpack

from module.config.utils import get_server_last_update
from module.exercise import assets as exercise_assets
from module.exercise.combat import ExerciseCombat
from module.logger import logger
from module.ocr.ocr import Digit, Ocr, OcrOptions, OcrRegions, OcrYuv, ocr_options


class DatedDuration(Ocr[timedelta]):
    def __init__(
        self,
        buttons: OcrRegions,
        options: OcrOptions | None = None,
        **settings: Unpack[OcrOptions],
    ) -> None:
        effective_settings: OcrOptions = settings
        if options is None:
            effective_settings = {"lang": "cnocr", **settings}
        super().__init__(
            buttons,
            options=ocr_options(options, effective_settings, alphabet="0123456789:IDS天日d"),
        )

    def after_process(self, result: str) -> timedelta:
        normalized = result.replace("I", "1").replace("D", "0").replace("S", "5")
        return self.parse_time(normalized)

    @staticmethod
    def parse_time(string: str) -> timedelta:
        """解析带天数的时长；识别失败时返回零时长。"""
        result = re.search(r"(\d{1,2})\D?(\d{1,2}):?(\d{2}):?(\d{2})", string)
        if result:
            result = [int(s) for s in result.groups()]
            return timedelta(days=result[0], hours=result[1], minutes=result[2], seconds=result[3])
        logger.warning(f"Invalid dated duration: {string}")
        return timedelta(days=0, hours=0, minutes=0, seconds=0)


class DatedDurationYuv(DatedDuration, OcrYuv[timedelta]):
    pass


OCR_EXERCISE_REMAIN = Digit(exercise_assets.OCR_EXERCISE_REMAIN, letter=(173, 247, 74), threshold=128)
OCR_PERIOD_REMAIN = DatedDuration(exercise_assets.OCR_PERIOD_REMAIN, letter=(255, 255, 255), threshold=128)
ADMIRAL_TRIAL_HOUR_INTERVAL: dict[str, tuple[int, int]] = {
    "sun18": (6, 0),
    "sun12": (12, 6),
    "sun0": (24, 12),
    "sat18": (30, 24),
    "sat12": (36, 30),
    "sat0": (48, 36),
    "fri18": (56, 48),
}


class Exercise(ExerciseCombat):
    opponent_change_count = 0
    remain = 0
    preserve = 0

    def _new_opponent(self) -> None:
        logger.info("New opponent")
        self.appear_then_click(exercise_assets.NEW_OPPONENT)
        self.opponent_change_count += 1

        logger.attr("Change_opponent_count", self.opponent_change_count)
        self.config.set_record(Exercise_OpponentRefreshValue=self.opponent_change_count)

        self.ensure_no_info_bar(timeout=3)

    def _opponent_fleet_check_all(self) -> None:
        if self.config.Exercise_OpponentChooseMode != "leftmost":
            super()._opponent_fleet_check_all()

    def _opponent_sort(self, method: str | None = None) -> list[int]:
        if method is None:
            method = self.config.Exercise_OpponentChooseMode
        if method != "leftmost":
            return super()._opponent_sort(method=method)
        return [0, 1, 2, 3]

    def _exercise_once(self) -> bool:
        """执行一次演习，并处理刷新对手和战斗失败。"""
        self._opponent_fleet_check_all()
        while 1:
            for opponent in self._opponent_sort():
                logger.hr(f"Opponent {opponent}", level=2)
                success = self._combat(opponent)
                if success:
                    return success

            if self.opponent_change_count >= 5:
                return False

            self._new_opponent()
            self._opponent_fleet_check_all()
        return False

    def _exercise_easiest_else_exp(self) -> bool:
        """优先挑战最弱对手；刷新耗尽后改打经验最高者并接受败局，返回是否完成一次结算。"""
        method = "easiest_else_exp"
        restore = self.config.Exercise_LowHpThreshold
        threshold = self.config.Exercise_LowHpThreshold
        self._opponent_fleet_check_all()
        while 1:
            opponents = self._opponent_sort(method=method)
            logger.hr(f"Opponent {opponents[0]}", level=2)
            self.config.override(Exercise_LowHpThreshold=threshold)
            success = self._combat(opponents[0])
            if success:
                self.config.override(Exercise_LowHpThreshold=restore)
                return success
            if self.opponent_change_count < 5:
                logger.info("Cannot beat calculated easiest opponent, refresh")
                self._new_opponent()
                self._opponent_fleet_check_all()
                continue
            logger.info("Cannot beat calculated easiest opponent, MAX EXP then")
            method = "max_exp"
            threshold = 0
        return False

    def _get_opponent_change_count(self) -> int:
        """同日沿用已记录的刷新次数；跨日清零，重新获得五次刷新。"""
        record = self.config.Exercise_OpponentRefreshRecord
        update = get_server_last_update("00:00")
        if record.date() == update.date():
            return self.config.Exercise_OpponentRefreshValue
        self.config.set_record(Exercise_OpponentRefreshValue=0)
        return 0

    def _get_exercise_reset_remain(self) -> timedelta:
        return OCR_PERIOD_REMAIN.ocr_single(self.device.image)

    def _get_exercise_strategy(self) -> tuple[int, tuple[int, int] | None]:
        """返回保留次数和元帅冲刺的剩余小时区间；激进策略不设区间。"""
        if self.config.Exercise_ExerciseStrategy == "aggressive":
            preserve = 0
            admiral_interval = None
        else:
            preserve = 5
            admiral_interval = ADMIRAL_TRIAL_HOUR_INTERVAL[self.config.Exercise_ExerciseStrategy]

        return preserve, admiral_interval
