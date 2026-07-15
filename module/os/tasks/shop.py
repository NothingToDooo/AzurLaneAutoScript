from datetime import datetime, timedelta

from module.config.utils import get_os_next_reset, get_os_reset_remain, get_server_next_update
from module.os.map import OSMap


class OpsiShop(OSMap):
    def _os_shop_delay(self, *, not_empty: bool) -> datetime:
        """not_empty 表示本轮扫描过滤后存在候选商品；结合大世界重置日计算下次运行时间。"""
        next_reset = None

        if not_empty:
            next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
        else:
            remain = get_os_reset_remain()
            next_reset = get_os_next_reset()
            if remain == 0:
                next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate)
            elif remain < 7:
                next_reset -= timedelta(days=1)
            else:
                next_reset = get_server_next_update(self.config.Scheduler_ServerUpdate) + timedelta(days=6)
        return next_reset
