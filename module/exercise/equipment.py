from module.base.timer import Timer
from module.combat.assets import BATTLE_PREPARATION
from module.equipment.equipment_change import EquipmentChange
from module.exercise.assets import EQUIP_EDIT_ACTIVE, EQUIP_EDIT_INACTIVE, EQUIP_ENTER


class ExerciseEquipment(EquipmentChange):
    def _active_edit(self) -> None:
        timer = Timer(5)
        while 1:
            self.device.screenshot()

            if timer.reached() and self.appear_then_click(EQUIP_EDIT_INACTIVE):
                timer.reset()

            if self.appear(EQUIP_EDIT_ACTIVE):
                self.device.sleep((0.2, 0.3))
                break

    def _inactive_edit(self) -> None:
        timer = Timer(5)
        while 1:
            self.device.screenshot()

            if timer.reached() and self.appear_then_click(EQUIP_EDIT_ACTIVE):
                timer.reset()

            if self.appear(EQUIP_EDIT_INACTIVE):
                self.device.sleep((0.2, 0.3))
                break

    def _equipment_take_on(self) -> None:
        self._active_edit()
        self.fleet_equipment_take_on_preset(
            preset_record=self.config.EXERCISE_FLEET_EQUIPMENT,
            enter=EQUIP_ENTER,
            long_click=True,
            out=BATTLE_PREPARATION,
        )
        self._inactive_edit()

    def _equipment_take_off(self) -> None:
        self._active_edit()
        self.fleet_equipment_take_off(enter=EQUIP_ENTER, long_click=True, out=BATTLE_PREPARATION)
        self._inactive_edit()
