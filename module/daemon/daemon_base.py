from typing import TYPE_CHECKING

from module.base.base import ModuleBase

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


class DaemonBase(ModuleBase):
    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
    ) -> None:
        super().__init__(config, device=device)
        self.device.disable_stuck_detection()
