import time
from pathlib import Path

import numpy as np

# os.chdir('../')
print(Path.cwd())
import module.config.server as server

server.server = "cn"  # Don't need to edit, it's used to avoid error.

from module.config.config import AzurLaneConfig
from module.device.device import Device


class EmulatorChecker(Device):
    def stress_test(self):
        record = []
        count = 0
        self.screenshot_nemu_ipc()
        while 1:
            t0 = time.time()
            self.screenshot_nemu_ipc()
            # self.click_minitouch(1270, 360)

            cost = time.time() - t0
            record.append(cost)
            count += 1
            print(count, np.round(np.mean(record), 3), np.round(np.std(record), 3))


class Config:
    SERIAL = "127.0.0.1:5555"
    # SERIAL = '127.0.0.1:62001'
    # SERIAL = '127.0.0.1:7555'
    # SERIAL = 'emulator-5554'
    # SERIAL = '127.0.0.1:21503'

    Emulator_ScreenshotMethod = "nemu_ipc"

    Emulator_ControlMethod = "minitouch"


az = EmulatorChecker(AzurLaneConfig("template").merge(Config()))
az.stress_test()
