from typing import TYPE_CHECKING

from module.base.base import ModuleBase
from module.base.utils import ColorBarOptions, color_bar_percentage
from module.combat_ui import assets as combat_ui_assets
from module.exercise import assets as exercise_assets
from module.logger import logger

if TYPE_CHECKING:
    from module.base.button import Button
    from module.base.timer import Timer
    from module.base.type_alias import Area, Color, ImageArray

NEW_HP_BAR_PAUSES = (
    combat_ui_assets.PAUSE_New,
    combat_ui_assets.PAUSE_Iridescent_Fantasy,
    combat_ui_assets.PAUSE_Neon,
    combat_ui_assets.PAUSE_Christmas,
    combat_ui_assets.PAUSE_Cyber,
    combat_ui_assets.PAUSE_HolyLight,
    combat_ui_assets.PAUSE_Pharaoh,
    combat_ui_assets.PAUSE_Nurse,
    combat_ui_assets.PAUSE_Devil,
    combat_ui_assets.PAUSE_Seaside,
    combat_ui_assets.PAUSE_Star,
    combat_ui_assets.PAUSE_Ninja,
    combat_ui_assets.PAUSE_ShadowPuppetry,
    combat_ui_assets.PAUSE_MaidCafe,
    combat_ui_assets.PAUSE_Ancient,
    combat_ui_assets.PAUSE_SpringInn,
    combat_ui_assets.PAUSE_ElvenVine,
    combat_ui_assets.PAUSE_GildedReverie,
    combat_ui_assets.PAUSE_AzureCore,
)


class HpDaemon(ModuleBase):
    attacker_hp = 1.0
    defender_hp = 1.0
    low_hp_confirm_timer: Timer

    @staticmethod
    def _calculate_hp(
        image: ImageArray,
        area: Area,
        options: ColorBarOptions | None = None,
        prev_color: Color = (239, 32, 33),
    ) -> float:
        """返回指定血条区域的剩余比例，范围为 0～1。"""
        if options is None:
            options = ColorBarOptions(starter=2)
        return color_bar_percentage(image, area, prev_color=prev_color, options=options)

    @staticmethod
    def _hp_options(*, reverse: bool) -> ColorBarOptions:
        return ColorBarOptions(reverse=reverse, starter=2)

    def _show_hp(self, low_hp_time: float = 0.0) -> None:
        attacker_hp = str(int(self.attacker_hp * 100)).rjust(2, "0") + "%"
        defender_hp = str(int(self.defender_hp * 100)).rjust(2, "0") + "%"
        text = f"[{attacker_hp} - {defender_hp}]"
        if low_hp_time:
            text += f" - Low HP: {str(round(low_hp_time, 3)).ljust(5, '0')}s"
        logger.info(text)

    def _at_low_hp(self, image: ImageArray, pause: Button | None = combat_ui_assets.PAUSE) -> bool:
        if pause == combat_ui_assets.PAUSE:
            self.attacker_hp = self._calculate_hp(
                image, area=exercise_assets.ATTACKER_HP_AREA.area, options=self._hp_options(reverse=True)
            )
            self.defender_hp = self._calculate_hp(
                image, area=exercise_assets.DEFENDER_HP_AREA.area, options=self._hp_options(reverse=False)
            )
        elif pause in NEW_HP_BAR_PAUSES:
            self.attacker_hp = self._calculate_hp(
                image, area=exercise_assets.ATTACKER_HP_AREA_New.area, options=self._hp_options(reverse=True)
            )
            self.defender_hp = self._calculate_hp(
                image, area=exercise_assets.DEFENDER_HP_AREA_New.area, options=self._hp_options(reverse=True)
            )
        else:
            logger.warning(f"_at_low_hp received unknown pause: {pause}")
            self.attacker_hp = self._calculate_hp(
                image, area=exercise_assets.ATTACKER_HP_AREA.area, options=self._hp_options(reverse=True)
            )
            self.defender_hp = self._calculate_hp(
                image, area=exercise_assets.DEFENDER_HP_AREA.area, options=self._hp_options(reverse=False)
            )

        # 对手已被击败，或血条被遮挡。
        if self.defender_hp < 0.01:
            self.low_hp_confirm_timer.reset()
        if 0.01 < self.attacker_hp <= self.config.Exercise_LowHpThreshold:
            if self.low_hp_confirm_timer.reached() and self.low_hp_confirm_timer.current_time() < 300:
                self._show_hp(self.low_hp_confirm_timer.current_time())
                return True
            return False
        self.low_hp_confirm_timer.reset()
        return False
