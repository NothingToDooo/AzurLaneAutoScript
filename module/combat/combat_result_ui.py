from typing import Protocol, override


class CombatResultRuntime(Protocol):
    def handle_exp_info(self) -> bool: ...


class CombatResultUi(Protocol):
    """战斗结算页的可替换 UI 行为。"""

    def handle_experience_result(self, runtime: CombatResultRuntime) -> bool: ...


class _StandardCombatResultUi(CombatResultUi):
    @override
    def handle_experience_result(self, runtime: CombatResultRuntime) -> bool:
        # 保留非声明式 runtime 的 virtual override，例如 Guild、Raid 与 OS combat。
        return runtime.handle_exp_info()


STANDARD_COMBAT_RESULT_UI: CombatResultUi = _StandardCombatResultUi()
