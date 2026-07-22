import json
from typing import TYPE_CHECKING

from module.base.decorator import cached_property, del_cached_property
from module.config.deep import deep_get
from module.device.mumu_instance import MuMuInstance, resolve_mumu_instance
from module.device.service_retry import session_retry
from module.exception import HumanTakeoverRequiredError
from module.logger import logger

if TYPE_CHECKING:
    from module.device.contracts import MumuSession


class MumuRuntimeBase:
    """Windows MuMu 实例与运行时检查的基层。"""

    _serial_bound_cached_properties = (
        "nemud_app_keep_alive",
        "nemud_player_version",
        "is_mumu_over_version_400",
        "is_mumu_over_version_356",
    )

    def __init__(self, session: MumuSession) -> None:
        self.session = session

    @property
    def serial(self) -> str:
        return self.session.serial

    @property
    def is_mumu_family(self) -> bool:
        return self.session.is_mumu_family

    @property
    def is_mumu12_family(self) -> bool:
        return self.session.is_mumu12_family

    def invalidate_serial(self) -> None:
        """清除由旧 serial 派生的 MuMu 运行时缓存。"""
        for name in self._serial_bound_cached_properties:
            del_cached_property(self, name)

    @cached_property
    def emulator_instance(self) -> MuMuInstance:
        config = self.session.config
        return resolve_mumu_instance(config.Emulator_MuMuPath, config.Emulator_Serial)

    def check_after_connected(self) -> None:
        self.check_mumu_app_keep_alive()

    @cached_property
    @session_retry
    def nemud_app_keep_alive(self) -> str:
        res = self.session.adb_getprop("nemud.app_keep_alive")
        logger.attr("nemud.app_keep_alive", res)
        return res

    @cached_property
    @session_retry
    def nemud_player_version(self) -> str:
        # [nemud.player_product_version]: [3.8.27.2950]
        res = self.session.adb_getprop("nemud.player_version")
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
            raise HumanTakeoverRequiredError
        logger.warning(f"Invalid nemud.app_keep_alive value: {value}")
        return False

    def check_mumu_app_keep_alive_400(self) -> bool:
        instance = self.emulator_instance
        file = instance.config_path("customer_config.json")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning(f"Failed to check check_mumu_app_keep_alive, file {file} not exists")
            return False

        value = deep_get(data, keys="customer.app_keptlive", default=None)
        logger.attr("customer.app_keptlive", value)
        if str(value).lower() == "true":
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('Please turn off "Keep alive in the background" in the settings or MuMuPlayer')
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise HumanTakeoverRequiredError
        return True

    @cached_property
    def is_mumu_over_version_400(self) -> bool:
        if not self.is_mumu_family:
            return False
        # 4.0 及以上版本没有 getprop 信息。
        return self.nemud_player_version == ""

    @cached_property
    def is_mumu_over_version_356(self) -> bool:
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return True
        return self.nemud_app_keep_alive != ""

    def diagnose_adb_connect_refused(self) -> None:
        self.check_mumu_bridge_network()

    def check_mumu_bridge_network(self) -> bool:
        """False 表示找不到实例或配置文件，无法执行检查。"""
        if not self.is_mumu12_family:
            return True

        file = self.emulator_instance.config_path("customer_config.json")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning(f"Failed to check check_mumu_bridge_network, file {file} not exists")
            return False

        value = deep_get(data, keys="customer.network_bridge_opened", default=None)
        logger.attr("customer.network_bridge_opened", value)
        if str(value).lower() == "true":
            logger.critical('Please turn off "Network Bridging" in the settings of MuMuPlayer')
            logger.critical("请在MuMU模拟器设置中关闭 网络桥接")
            raise HumanTakeoverRequiredError
        return True
