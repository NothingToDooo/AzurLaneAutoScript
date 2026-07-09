from contextlib import suppress

from module.coalition.coalition import Coalition
from module.config.config import TaskEnd


class CoalitionSP(Coalition):
    def run(self, event="", mode="", fleet="", total=0):
        with suppress(TaskEnd):
            super().run(event=event, mode=mode or "sp", fleet=fleet, total=total or 1)
        if self.run_count > 0:
            self.config.task_delay(server_update=True)
        else:
            self.config.task_stop()
