class CampaignEnd(Exception):  # ruff:ignore[error-suffix-on-exception-name] - 表示关卡流程正常结束。
    pass


class OilExhausted(Exception):  # ruff:ignore[error-suffix-on-exception-name] - 表示资源耗尽的业务停止条件。
    pass


class OilMaxed(Exception):  # ruff:ignore[error-suffix-on-exception-name] - 表示资源达到上限的业务停止条件。
    pass


class MapDetectionError(Exception):
    pass


class MapWalkError(Exception):
    pass


class MapEnemyMoved(Exception):  # ruff:ignore[error-suffix-on-exception-name] - 通知调用方重新扫描并计算路径。
    pass


class CampaignNameError(Exception):
    pass


class ScriptError(Exception):
    # 通常表示开发错误，偶尔也可能由随机故障触发。
    pass


class CampaignSelectionError(Exception):
    pass


class MapAchievementReached(Exception):  # ruff:ignore[error-suffix-on-exception-name] - 表示地图成就条件已满足。
    pass


class GameStuckError(Exception):
    pass


class GameBugError(Exception):
    # 游戏客户端异常超出 Alas 的处理范围，通常需要重启。
    pass


class GameTooManyClickError(Exception):
    pass


class EmulatorNotRunningError(Exception):
    pass


class GameNotRunningError(Exception):
    pass


class GamePageUnknownError(Exception):
    pass


class HumanTakeoverRequiredError(Exception):
    # 自动处理失败时请求人工接管，常见原因是配置错误。
    pass


class HardFleetRequirementsError(HumanTakeoverRequiredError):
    """困难关卡舰队要求未满足，允许 GemsFarming 先补齐空位。"""
