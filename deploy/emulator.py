import asyncio
import filecmp
import os
import re
import shutil
import subprocess
import winreg
from pathlib import Path

from deploy.logger import logger
from deploy.utils import cached_property


class VirtualBoxEmulator:
    UNINSTALL_REG = "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
    UNINSTALL_REG_2 = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"

    def __init__(self, name, root_path, adb_path, vbox_path, vbox_name):
        """
        Args:
            name (str): Emulator name in windows uninstall list.
            root_path (str): Relative path from uninstall.exe to emulator installation folder.
            adb_path (str, list[str]): Relative path to adb.exe. List of str if there are multiple adb in emulator.
            vbox_path (str): Relative path to virtual box folder.
            vbox_name (str): Regular Expression to match the name of .vbox file.
        """
        self.name = name
        self.root_path = root_path
        self.adb_path = adb_path if isinstance(adb_path, list) else [adb_path]
        self.vbox_path = vbox_path
        self.vbox_name = vbox_name

    @cached_property
    def root(self):
        """
        Returns:
            str: Root installation folder of emulator.

        Raises:
            FileNotFoundError: If emulator not installed.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{self.UNINSTALL_REG}\\{self.name}", 0) as reg:
                res = winreg.QueryValueEx(reg, "UninstallString")[0]
        except FileNotFoundError:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{self.UNINSTALL_REG_2}\\{self.name}", 0) as reg:
                res = winreg.QueryValueEx(reg, "UninstallString")[0]

        file = re.search('"(.*?)"', res)
        file = file.group(1) if file else res
        return str((Path(file).parent / self.root_path).resolve())

    @cached_property
    def adb_binary(self):
        return [str((Path(self.root) / a).resolve()) for a in self.adb_path]

    @cached_property
    def adb_backup(self):
        files = []
        for adb in self.adb_binary:
            for n in range(10):
                backup = f"{adb}.bak{n}" if n else f"{adb}.bak"
                if Path(backup).exists():
                    continue
                files.append(backup)
                break
        return files

    @cached_property
    def serial(self):
        """
        Returns:
            list[str]: Such as ['127.0.0.1:62001', '127.0.0.1:62025']
        """
        vbox = []
        for path, _folders, files in os.walk(Path(self.root) / self.vbox_path):
            for file in files:
                if re.match(self.vbox_name, file):
                    file = str(Path(path) / file)
                    vbox.append(file)

        serial = []
        for file in vbox:
            with Path(file).open(encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # <Forwarding name="port2" proto="1" hostip="127.0.0.1" hostport="62026" guestport="5555"/>
                    res = re.search('<*?hostport="(.*?)".*?guestport="5555"/>', line)
                    if res:
                        serial.append(f"127.0.0.1:{res.group(1)}")

        return serial

    def adb_replace(self, adb):
        """
        Backup the adb in emulator folder to xxx.bak, replace it with your adb.
        Need to call `adb kill-server` before replacing.

        Args:
            adb (str): Absolute path to adb.exe
        """
        for ori, bak in zip(self.adb_binary, self.adb_backup, strict=True):
            logger.info(f"Replacing {ori}")
            try:
                if Path(ori).exists():
                    if filecmp.cmp(adb, ori, shallow=True):
                        logger.info(f"{adb} is same as {ori}, skip")
                    else:
                        logger.info(f"{ori} -----> {bak}")
                        shutil.move(ori, bak)
                        logger.info(f"{adb} -----> {ori}")
                        shutil.copy(adb, ori)
                else:
                    logger.info(f"{ori} not exists, skip")
            except OSError as e:
                logger.warning(f"Failed to replace {ori}, {e}")

    def adb_recover(self):
        """Revert adb replacement"""
        for ori in self.adb_binary:
            logger.info(f"Recovering {ori}")
            bak = f"{ori}.bak"
            if Path(bak).exists():
                logger.info(f"Delete {ori}")
                if Path(ori).exists():
                    Path(ori).unlink()
                logger.info(f"{bak} -----> {ori}")
                shutil.move(bak, ori)
            else:
                logger.info(f"Not exists {bak}, skip")


mumu_player = VirtualBoxEmulator(
    name="Nemu", root_path=".", adb_path="./vmonitor/bin/adb_server.exe", vbox_path="./vms", vbox_name=".*.nemu$"
)


class EmulatorConnect:
    SUPPORTED_EMULATORS = [mumu_player]

    def __init__(self, adb="adb.exe"):
        self.adb_binary = adb

    def _execute(self, cmd, timeout=10, output=True):
        """
        Returns:
            Object: Stdout(str) of cmd if output,
                    return code(int) of cmd if not output.
        """
        if not output:
            cmd.extend([">nul", "2>nul"])
        logger.info(" ".join(cmd))
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            ret_code = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            ret_code = 1
            logger.info(f"TimeoutExpired, stdout={stdout}, stderr={stderr}")
        if output:
            return stdout
        return ret_code

    @cached_property
    def emulators(self):
        """
        Returns:
            list: List of installed emulators on current computer.
        """
        emulators = []
        for emulator in self.SUPPORTED_EMULATORS:
            try:
                serial = emulator.serial
                emulators.append(emulator)
            except FileNotFoundError:
                continue
            if len(serial):
                logger.info(f"Emulator {emulator.name} found, instances: {serial}")

        return emulators

    def devices(self):
        """
        Returns:
            list[str]: Connected devices in adb
        """
        result = self._execute([self.adb_binary, "devices"]).decode()
        devices = []
        for line in result.replace("\r\r\n", "\n").replace("\r\n", "\n").split("\n"):
            if line.startswith("List") or "\t" not in line:
                continue
            serial, status = line.split("\t")
            if status == "device":
                devices.append(serial)

        logger.info(f"Devices: {devices}")
        return devices

    def adb_kill(self):
        # self._execute([self.adb_binary, 'devices'])
        # self._execute([self.adb_binary, 'kill-server'])

        # Just kill it, because some adb don't obey.
        logger.info("Kill all known ADB")
        for exe in [
            # 通用 ADB 进程。
            "adb.exe",
            # MuMu 模拟器。
            "adb_server.exe",
        ]:
            ret_code = self._execute(["taskkill", "/f", "/im", exe], output=False)
            if ret_code == 0:
                logger.info(f"Task {exe} killed")
            elif ret_code == 128:
                logger.info(f"Task {exe} not found")
            else:
                logger.info(f"Error occurred when killing task {exe}, return code {ret_code}")

    @cached_property
    def serial(self):
        """
        Returns:
            list[str]: All available emulator serial on current computer.
        """
        serial = ["127.0.0.1:7555"]
        for emulator in self.emulators:
            serial += emulator.serial
            for s in emulator.serial:
                _ip, port = s.split(":")
                port = int(port) - 1
                if 5554 <= int(port) < 5600:
                    serial.append(f"emulator-{port}")

        return serial

    def brute_force_connect(self):
        """Brute-force connect all available emulator instances"""
        self.devices()

        async def connect():
            await asyncio.gather(
                *[asyncio.create_subprocess_exec(self.adb_binary, "connect", serial) for serial in self.serial]
            )

        asyncio.run(connect())

        return self.devices()

    def adb_replace(self, adb=None):
        """
        不同版本的 ADB 启动时会互相杀掉。
        MuMu 使用自己的 ADB，而不是系统 PATH 里的 ADB。
        因此 MuMu 启动时会杀掉 Alas 正在使用的 adb.exe。
        替换模拟器目录里的 ADB 是最简单的处理方式。

        Args:
            adb (str): Absolute path to adb.exe
        """
        self.adb_kill()
        for emulator in self.emulators:
            emulator.adb_replace(adb if adb is not None else self.adb_binary)
        self.brute_force_connect()

    def adb_recover(self):
        """Revert adb replacement"""
        self.adb_kill()
        for emulator in self.emulators:
            emulator.adb_recover()
        self.brute_force_connect()


if __name__ == "__main__":
    emu = EmulatorConnect()
    logger.info(emu.brute_force_connect())
