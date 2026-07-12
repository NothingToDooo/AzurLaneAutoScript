class CampaignEnd(Exception):
    pass


class OilExhausted(Exception):
    pass


class OilMaxed(Exception):
    pass


class MapDetectionError(Exception):
    pass


class MapWalkError(Exception):
    pass


class MapEnemyMoved(Exception):
    pass


class CampaignNameError(Exception):
    pass


class ScriptError(Exception):
    # 通常表示开发错误，偶尔也可能由随机故障触发。
    pass


class ScriptEnd(Exception):
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


class RequestHumanTakeover(Exception):
    # 自动处理失败时请求人工接管，常见原因是配置错误。
    pass


class HardNotSatisfied(RequestHumanTakeover):
    """困难关卡舰队要求未满足，允许 GemsFarming 先补齐空位。"""
