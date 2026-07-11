from typing import TYPE_CHECKING

from module.base.base import ModuleBase

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


class DaemonBase(ModuleBase):
    def __init__(
        self,
        config: AzurLaneConfig | str,
        device: Device | str | None = None,
        task: str | None = None,
    ) -> None:
        super().__init__(config, device=device, task=task)
        self.device.disable_stuck_detection()
