import json
from pathlib import Path

from module.base.decorator import cached_property
from module.config.deep import deep_get
from module.device.connection import Connection, retry
from module.device.mumu import mumu12_serial_to_id
from module.device.platform.emulator_base import (
    EmulatorInstanceBase,
    EmulatorManagerBase,
    remove_duplicated_path,
)
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.map.map_grids import SelectedGrids


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
    return mumu12_serial_to_id(serial)


class PlatformBase(Connection):
    """
    Windows 模拟器平台的基类。
    """

    _serial_bound_cached_properties = (
        "emulator_instance",
        "nemud_app_keep_alive",
        "nemud_player_version",
        "is_mumu_over_version_400",
        "is_mumu_over_version_356",
    )

    emulator_manager: EmulatorManagerBase

    @cached_property
    def emulator_instance(self) -> EmulatorInstanceBase | None:
        """
        返回：
            EmulatorInstanceBase：模拟器实例；找不到时返回 None。
        """
        return self.find_emulator_instance(serial=self.serial)

    def _check_after_connected(self) -> None:
        """
        ADB 连接建立后检查 MuMu 运行设置。
        """
        self.check_mumu_app_keep_alive()

    @cached_property
    @retry
    def nemud_app_keep_alive(self) -> str:
        res = self.adb_getprop("nemud.app_keep_alive")
        logger.attr("nemud.app_keep_alive", res)
        return res

    @cached_property
    @retry
    def nemud_player_version(self) -> str:
        # [nemud.player_product_version]: [3.8.27.2950]
        res = self.adb_getprop("nemud.player_version")
        logger.attr("nemud.player_version", res)
        return res

    def check_mumu_app_keep_alive(self) -> bool:
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return self.check_mumu_app_keep_alive_400()

        value = self.nemud_app_keep_alive
        if value == "":
            # 旧版 MuMu 无法通过该属性判断后台保活。
            return True
        if value == "false":
            # 已关闭。
            return True
        if value == "true":
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover
        logger.warning(f"Invalid nemud.app_keep_alive value: {value}")
        return False

    def check_mumu_app_keep_alive_400(self) -> bool:
        """
        检查 MuMu 4.0+ 配置中的后台保活。
        """
        instance = self.emulator_instance
        if instance is None:
            logger.warning("Failed to check check_mumu_app_keep_alive as emulator_instance is None")
            return False

        file = instance.mumu_vms_config("customer_config.json")
        try:
            data = json.loads(Path(file).read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning(f"Failed to check check_mumu_app_keep_alive, file {file} not exists")
            return False

        value = deep_get(data, keys="customer.app_keptlive", default=None)
        logger.attr("customer.app_keptlive", value)
        if str(value).lower() == "true":
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('Please turn off "Keep alive in the background" in the settings or MuMuPlayer')
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover
        return True

    @cached_property
    def is_mumu_over_version_400(self) -> bool:
        if not self.is_mumu_family:
            return False
        # 4.0 及以上版本没有 getprop 信息。
        return self.nemud_player_version == ""

    @cached_property
    def is_mumu_over_version_356(self) -> bool:
        """
        返回：
            bool：MuMu12 版本是否不低于 3.5.6。
        """
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return True
        return self.nemud_app_keep_alive != ""

    def _diagnose_adb_connect_refused(self) -> None:
        """
        ADB TCP 连接被拒绝时检查 MuMu 实例配置。
        """
        self.check_mumu_bridge_network()

    def check_mumu_bridge_network(self) -> bool:
        """
        返回：
            bool：True 表示检查通过，False 表示跳过检查。
        """
        if not self.is_mumu12_family:
            return True

        instance = self.find_emulator_instance(serial=self.serial)
        if instance is None:
            logger.warning("Failed to check check_mumu_bridge_network, emulator instance not found")
            return False

        file = instance.mumu_vms_config("customer_config.json")
        try:
            data = json.loads(Path(file).read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning(f"Failed to check check_mumu_bridge_network, file {file} not exists")
            return False

        value = deep_get(data, keys="customer.network_bridge_opened", default=None)
        logger.attr("customer.network_bridge_opened", value)
        if str(value).lower() == "true":
            logger.critical('Please turn off "Network Bridging" in the settings of MuMuPlayer')
            logger.critical("请在MuMU模拟器设置中关闭 网络桥接")
            raise RequestHumanTakeover
        return True

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

    def _narrow_emulator_instance_by_running_path(
        self, instances: SelectedGrids, search_args: dict[str, str], path: str
    ) -> EmulatorInstanceBase | None:
        """
        在当前查询条件上追加运行中的模拟器路径。

        返回：
            EmulatorInstanceBase：找到的实例；找不到唯一实例时返回 None。
        """
        search_args["path"] = path
        select = instances.select(**search_args)
        if select.count == 0:
            logger.warning(f"No emulator instances with {search_args}, running path invalid")
            search_args.pop("path")
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
        running = remove_duplicated_path(list(self.emulator_manager.iter_running_emulator()))
        logger.info("Running emulators")
        for exe in running:
            logger.info(exe)
        if len(running) != 1:
            return None

        logger.info("Only one running emulator")
        # 等价于按路径查找。
        return self._narrow_emulator_instance_by_running_path(instances, search_args, running[0])

    def find_emulator_instance(self, serial: str) -> EmulatorInstanceBase | None:
        """
        参数：
            serial：类似 "127.0.0.1:16384" 的 serial。

        返回：
            EmulatorInstance：模拟器实例；找不到时返回 None。
        """
        logger.hr("Find emulator instance", level=2)
        instances = SelectedGrids(self.emulator_manager.all_emulator_instances)
        self._log_emulator_instances(instances)
        search_args = {"serial": serial}

        # 按 serial 查找。
        select = instances.select(**search_args)
        if select.count == 0:
            logger.warning(f"No emulator instance with {search_args}, serial invalid")
            return None
        if select.count == 1:
            return self._log_found_emulator_instance(select[0])

        # MuMu12 额外修正：serial 对应多个候选时，检查实例 ID。
        instance = self._find_mumu12_instance_by_serial_id(instances)
        if instance is not None:
            return instance

        # 仍有太多实例时，从正在运行的模拟器里查找。
        instance = self._find_single_running_emulator_instance(instances, search_args)
        if instance is not None:
            return instance

        # 仍然无法唯一确定实例。
        logger.warning(f"Found multiple emulator instances with {search_args}")
        return None
