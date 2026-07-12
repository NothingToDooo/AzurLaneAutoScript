import time
from pathlib import Path

import numpy as np

from module.config.config import AzurLaneConfig
from module.device.device import Device


class EmulatorChecker(Device):
    def stress_test(self) -> None:
        record: list[float] = []
        count = 0
        self.screenshot_nemu_ipc()
        while 1:
            t0 = time.time()
            self.screenshot_nemu_ipc()

            cost = time.time() - t0
            record.append(cost)
            count += 1
            print(count, np.round(np.mean(record), 3), np.round(np.std(record), 3))


class Config:
    Emulator_Serial = "127.0.0.1:16384"


def main() -> None:
    print(Path.cwd())
    az = EmulatorChecker(AzurLaneConfig("template").merge(Config()))
    az.stress_test()


if __name__ == "__main__":
    main()
