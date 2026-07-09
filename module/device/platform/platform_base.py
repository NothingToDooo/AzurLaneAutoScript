from dataclasses import dataclass

from module.base.decorator import cached_property, del_cached_property
from module.device.connection import Connection
from module.device.platform.emulator_base import (
    EmulatorBase,
    EmulatorInstanceBase,
    EmulatorManagerBase,
    remove_duplicated_path,
)
from module.logger import logger
from module.map.map_grids import SelectedGrids


@dataclass
class EmulatorInfo:
    emulator: str = ""
    name: str = ""
    path: str = ""


def serial_to_id(serial: str):
    """
    从 serial 推算 MuMu 实例 ID。

    例如：
        "127.0.0.1:16384" -> 0
        "127.0.0.1:16416" -> 1
        16414 到 16418 端口 -> 1

    返回：
        int：实例 ID；无法推算时返回 None。
    """
    try:
        port = int(serial.split(":")[1])
    except IndexError, ValueError:
        return None
    index, offset = divmod(port - 16384 + 16, 32)
    offset -= 16
    if 0 <= index < 32 and offset in [-2, -1, 0, 1, 2]:
        return index
    return None


class PlatformBase(Connection, EmulatorManagerBase):
    """
    Windows 模拟器平台的基类。
    """

    @cached_property
    def emulator_info(self) -> EmulatorInfo:
        def parse_info(value):
            if isinstance(value, str):
                value = value.strip().replace("\n", "")
                if value in ["None", "False", "True", "auto"]:
                    value = ""
                return value
            return ""

        emulator = parse_info(self.config.EmulatorInfo_Emulator) or EmulatorBase.MuMuPlayer12
        name = parse_info(self.config.EmulatorInfo_name)
        path = parse_info(self.config.EmulatorInfo_path)

        return EmulatorInfo(
            emulator=emulator,
            name=name,
            path=path,
        )

    @cached_property
    def emulator_instance(self) -> EmulatorInstanceBase | None:
        """
        返回：
            EmulatorInstanceBase：模拟器实例；找不到时返回 None。
        """
        data = self.emulator_info
        old_info = {
            "emulator": data.emulator,
            "path": data.path,
            "name": data.name,
        }
        instance = self.find_emulator_instance(
            serial=self.serial,
            name=data.name,
            path=data.path,
            emulator=data.emulator,
        )

        # 写入完整模拟器信息。
        if instance is not None:
            new_info = {
                "emulator": instance.type,
                "path": instance.path,
                "name": instance.name,
            }
            if new_info != old_info:
                with self.config.multi_set():
                    self.config.EmulatorInfo_Emulator = instance.type
                    self.config.EmulatorInfo_name = instance.name
                    self.config.EmulatorInfo_path = instance.path
                del_cached_property(self, "emulator_info")

        return instance

    @staticmethod
    def _log_emulator_instances(instances: SelectedGrids) -> None:
        for instance in instances:
            logger.info(instance)

    @staticmethod
    def _log_found_emulator_instance(instance: EmulatorInstanceBase) -> EmulatorInstanceBase:
        logger.hr("Emulator instance", level=2)
        logger.info(f"Found emulator instance: {instance}")
        return instance

    def _find_mumu12_instance_by_serial_id(self, instances: SelectedGrids) -> EmulatorInstanceBase | None:
        """
        serial 对应多个候选时，用 MuMu12 实例 ID 做一次额外消歧。

        返回：
            EmulatorInstanceBase：找到的实例；找不到唯一实例时返回 None。
        """
        instance_id = serial_to_id(self.serial)
        if instance_id is None:
            return None

        select = instances.select(MuMuPlayer12_id=instance_id)
        # 这里只是试探，因此 select.count == 1 时不单独记录日志。
        if select.count == 1:
            return self._log_found_emulator_instance(select[0])
        return None

    def _narrow_emulator_instance(
        self,
        instances: SelectedGrids,
        search_args: dict[str, str],
        key: str,
        value: str | None,
        label: str,
    ) -> EmulatorInstanceBase | None:
        """
        在当前查询条件上追加一个用户 hint，并在 hint 无效时回滚。

        返回：
            EmulatorInstanceBase：找到的实例；找不到唯一实例时返回 None。
        """
        if not value:
            return None

        search_args[key] = value
        select = instances.select(**search_args)
        if select.count == 0:
            logger.warning(f"No emulator instances with {search_args}, {label} invalid")
            search_args.pop(key)
            return None
        if select.count == 1:
            return self._log_found_emulator_instance(select[0])
        return None

    def _find_single_running_emulator_instance(
        self, instances: SelectedGrids, search_args: dict[str, str]
    ) -> EmulatorInstanceBase | None:
        """
        当只剩一个正在运行的模拟器时，用它的路径作为最终消歧条件。

        返回：
            EmulatorInstanceBase：找到的实例；找不到唯一实例时返回 None。
        """
        running = remove_duplicated_path(list(self.iter_running_emulator()))
        logger.info("Running emulators")
        for exe in running:
            logger.info(exe)
        if len(running) != 1:
            return None

        logger.info("Only one running emulator")
        # 等价于按路径查找。
        return self._narrow_emulator_instance(instances, search_args, "path", running[0], "path")

    def find_emulator_instance(
        self, serial: str, name: str | None = None, path: str | None = None, emulator: str | None = None
    ) -> EmulatorInstanceBase | None:
        """
        参数：
            serial：类似 "127.0.0.1:5555" 的 serial。
            name：类似 "Nougat64" 的实例名称。
            path：类似 "C:/Program Files/MuMuPlayer-12.0/shell/MuMuPlayer.exe" 的模拟器安装路径。
            emulator：Emulator 类中定义的模拟器类型，例如 "MuMuPlayer12"。

        返回：
            EmulatorInstance：模拟器实例；找不到时返回 None。
        """
        logger.hr("Find emulator instance", level=2)
        instances = SelectedGrids(self.all_emulator_instances)
        self._log_emulator_instances(instances)
        search_args = {"serial": serial}

        # 按 serial 查找。
        select = instances.select(**search_args)
        if select.count == 0:
            logger.warning(f"No emulator instance with {search_args}, serial invalid")
            return None
        if select.count == 1:
            return self._log_found_emulator_instance(select[0])

        # MuMu12 额外修正。
        # MuMu12 的 vbox 配置中可能是 127.0.0.1:7555，但用户配置 serial=127.0.0.1:16xxx。
        # 遇到这种情况时，检查 serial 是否能和实例 ID 对应。
        instance = self._find_mumu12_instance_by_serial_id(instances)
        if instance is not None:
            return instance

        search_hints = [
            # 先按模拟器类型查找；这是用户最容易设置的项，因此更可信。
            # 给定 serial、name、path 后仍有多个实例时，按模拟器类型收窄。
            ("type", emulator, "type"),
            ("name", name, "name"),
            ("path", path, "path"),
        ]
        for key, value, label in search_hints:
            instance = self._narrow_emulator_instance(instances, search_args, key, value, label)
            if instance is not None:
                return instance

        # 仍有太多实例时，从正在运行的模拟器里查找。
        instance = self._find_single_running_emulator_instance(instances, search_args)
        if instance is not None:
            return instance

        # 仍然无法唯一确定实例。
        logger.warning(f"Found multiple emulator instances with {search_args}")
        return None
