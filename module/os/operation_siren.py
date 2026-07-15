from module.os.tasks.cross_month import OpsiCrossMonth
from module.os.tasks.explore import OpsiExplore
from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming
from module.os.tasks.month_boss import OpsiMonthBoss
from module.os.tasks.shop import OpsiShop
from module.os.tasks.stronghold import OpsiStronghold
from module.os.tasks.voucher import OpsiVoucher


class OperationSiren(
    OpsiShop,
    OpsiVoucher,
    OpsiMeowfficerFarming,
    OpsiStronghold,
    OpsiMonthBoss,
    OpsiExplore,
    OpsiCrossMonth,
):
    """聚合大世界各任务模块。"""
