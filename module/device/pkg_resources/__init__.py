import os
import re
import sys

from module.base.decorator import cached_property
from module.logger import logger

"""
替代很慢的 pkg_resources，只实现 adbutils 和 uiautomator2 会用到的最小接口。

用法：
```
# 必须在导入 adbutils 和 uiautomator2 前注入。
from module.device.pkg_resources import get_distribution
# 避免被导入优化删除。
_ = get_distribution
```
"""
# 注入 sys.modules，让依赖以为 pkg_resources 已经导入。
try:
    sys.modules["pkg_resources"] = sys.modules["module.device.pkg_resources"]
except KeyError:
    logger.error("Patch pkg_resources failed, patch module does not exists")


class FakeDistributionObject:
    def __init__(self, dist, version):
        self.dist = dist
        self.version = version

    def __str__(self):
        return f"{self.__class__.__name__}({self.dist}={self.version})"

    __repr__ = __str__


class PackageCache:
    @cached_property
    def site_packages(self):
        # 借用已安装依赖定位当前环境的 site-packages。
        import requests

        return os.path.abspath(os.path.join(requests.__file__, "../../"))

    @cached_property
    def dict_installed_packages(self):
        """
        返回：
            dict：key 为包名，value 为 FakeDistributionObject。
        """
        dic = {}
        for file in os.listdir(self.site_packages):
            # mxnet_cu101-1.6.0.dist-info
            # adbutils-0.11.0-py3.7.egg-info
            res = re.match(r"^([a-zA-Z0-9._]+)-([a-zA-Z0-9._]+)-", file)
            if res:
                version = res.group(2).removesuffix(".dist")
                # version = res.group(2)
                obj = FakeDistributionObject(
                    dist=res.group(1),
                    version=version,
                )
                dic[obj.dist] = obj

        return dic


PACKAGE_CACHE = PackageCache()


def resource_filename(*args):
    if args == ("adbutils", "binaries"):
        return os.path.abspath(os.path.join(PACKAGE_CACHE.site_packages, *args))
    return None


def get_distribution(dist):
    """返回当前依赖版本；这里只实现 adbutils 和 uiautomator2 需要的最小接口。"""
    if dist == "adbutils":
        return PACKAGE_CACHE.dict_installed_packages.get(
            "adbutils",
            FakeDistributionObject("adbutils", "0.11.0"),
        )
    if dist == "uiautomator2":
        return PACKAGE_CACHE.dict_installed_packages.get(
            "uiautomator2",
            FakeDistributionObject("uiautomator2", "2.16.17"),
        )
    return None


class DistributionNotFound(Exception):
    pass
