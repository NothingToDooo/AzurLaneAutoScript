import sys

from pydantic import BaseModel

from module.base.decorator import cached_property, del_cached_property
from module.device.connection import Connection
from module.device.method.utils import get_serial_pair
from module.device.platform.emulator_base import EmulatorInstanceBase, EmulatorManagerBase, remove_duplicated_path
from module.logger import logger
from module.map.map_grids import SelectedGrids


class EmulatorInfo(BaseModel):
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
    else:
        return None


class PlatformBase(Connection, EmulatorManagerBase):
    """
    Windows 模拟器平台的基类。

    每个 `Platform` 类需要实现以下接口：
    - all_emulators()
    - all_emulator_instances()
    - emulator_start()
    - emulator_stop()
    """

    def emulator_start(self):
        """
        启动模拟器并等待启动完成。

        - 需要自行重试。
        - 不要用固定 sleep 等待启动。
        """
        logger.info(f"Current platform {sys.platform} does not support emulator_start, skip")

    def emulator_stop(self):
        """
        停止模拟器。
        """
        logger.info(f"Current platform {sys.platform} does not support emulator_stop, skip")

    @cached_property
    def emulator_info(self) -> EmulatorInfo:
        emulator = self.config.EmulatorInfo_Emulator
        if emulator == "auto":
            emulator = ""

        def parse_info(value):
            if isinstance(value, str):
                value = value.strip().replace("\n", "")
                if value in ["None", "False", "True"]:
                    value = ""
                return value
            else:
                return ""

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
        # 将 emulator-5554 重定向到 127.0.0.1:5555。
        serial = self.serial
        port_serial, _ = get_serial_pair(self.serial)
        if port_serial is not None:
            serial = port_serial

        instance = self.find_emulator_instance(
            serial=serial,
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

    def find_emulator_instance(
        self, serial: str, name: str = None, path: str = None, emulator: str = None
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
        for instance in instances:
            logger.info(instance)
        search_args = {"serial": serial}

        # 按 serial 查找。
        select = instances.select(**search_args)
        if select.count == 0:
            logger.warning(f"No emulator instance with {search_args}, serial invalid")
            return None
        if select.count == 1:
            instance = select[0]
            logger.hr("Emulator instance", level=2)
            logger.info(f"Found emulator instance: {instance}")
            return instance

        # MuMu12 额外修正。
        # MuMu12 的 vbox 配置中可能是 127.0.0.1:7555，但用户配置 serial=127.0.0.1:16xxx。
        # 遇到这种情况时，检查 serial 是否能和实例 ID 对应。
        instance_id = serial_to_id(self.serial)
        if instance_id is not None:
            select = instances.select(MuMuPlayer12_id=instance_id)
            # 这里只是试探，因此 select.count == 1 时不单独记录日志。
            if select.count == 1:
                instance = select[0]
                logger.hr("Emulator instance", level=2)
                logger.info(f"Found emulator instance: {instance}")
                return instance

        # 先按模拟器类型查找；这是用户最容易设置的项，因此更可信。
        # 给定 serial、name、path 后仍有多个实例时，按模拟器类型收窄。
        if emulator:
            search_args["type"] = emulator
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f"No emulator instances with {search_args}, type invalid")
                search_args.pop("type")
            elif select.count == 1:
                instance = select[0]
                logger.hr("Emulator instance", level=2)
                logger.info(f"Found emulator instance: {instance}")
                return instance

        # 给定 serial 后仍有多个实例时，按名称查找。
        if name:
            search_args["name"] = name
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f"No emulator instances with {search_args}, name invalid")
                search_args.pop("name")
            elif select.count == 1:
                instance = select[0]
                logger.hr("Emulator instance", level=2)
                logger.info(f"Found emulator instance: {instance}")
                return instance

        # 给定 serial 和 name 后仍有多个实例时，按路径查找。
        if path:
            search_args["path"] = path
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f"No emulator instances with {search_args}, path invalid")
                search_args.pop("path")
            elif select.count == 1:
                instance = select[0]
                logger.hr("Emulator instance", level=2)
                logger.info(f"Found emulator instance: {instance}")
                return instance

        # 仍有太多实例时，从正在运行的模拟器里查找。
        running = remove_duplicated_path(list(self.iter_running_emulator()))
        logger.info("Running emulators")
        for exe in running:
            logger.info(exe)
        if len(running) == 1:
            logger.info("Only one running emulator")
            # 等价于按路径查找。
            search_args["path"] = running[0]
            select = instances.select(**search_args)
            if select.count == 0:
                logger.warning(f"No emulator instances with {search_args}, path invalid")
                search_args.pop("path")
            elif select.count == 1:
                instance = select[0]
                logger.hr("Emulator instance", level=2)
                logger.info(f"Found emulator instance: {instance}")
                return instance

        # 仍然无法唯一确定实例。
        logger.warning(f"Found multiple emulator instances with {search_args}")
        return None
