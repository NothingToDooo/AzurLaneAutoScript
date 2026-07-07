import os
import typing as t

import psutil

from deploy.Windows.config import DeployConfig
from deploy.Windows.logger import logger
from deploy.Windows.utils import DataProcessInfo, cached_property, iter_process


class AlasManager(DeployConfig):
    @cached_property
    def alas_folder(self):
        return [self.filepath(self.PythonExecutable), self.root_filepath]

    @cached_property
    def self_pid(self):
        return os.getpid()

    def list_process(self) -> list[DataProcessInfo]:
        logger.info("List process")
        process = list(iter_process())
        logger.info(f"Found {len(process)} processes")
        return process

    def iter_process_by_names(self, names, in_alas=False) -> t.Iterable[DataProcessInfo]:
        """
        Args:
            names (str, list[str]): process names, such as 'python.exe'
            in_alas (bool): If the output process must in Alas

        Yields:
            DataProcessInfo:
        """
        if not isinstance(names, list):
            names = [names]
        try:
            for proc in self.list_process():
                if not (proc.name and proc.name in names):
                    continue
                if proc.pid == self.self_pid:
                    continue
                if in_alas:
                    cmdline = proc.cmdline.replace(r"\\", "/").replace("\\", "/")
                    for folder in self.alas_folder:
                        if folder in cmdline:
                            yield proc
                else:
                    yield proc
        except Exception as e:
            logger.info(str(e))
            return False

    def kill_process(self, process: DataProcessInfo):
        try:
            proc = psutil.Process(process.pid)
            children = proc.children(recursive=True)
        except psutil.Error as e:
            logger.info(f"进程 {process.pid} 已不可用，跳过：{e}")
            return

        for child in children:
            try:
                logger.info(f"Kill child process: {child.pid}")
                child.kill()
            except psutil.Error as e:
                logger.info(f"子进程 {child.pid} 已不可用，跳过：{e}")

        try:
            logger.info(f"Kill process: {process.pid}")
            proc.kill()
        except psutil.Error as e:
            logger.info(f"进程 {process.pid} 已不可用，跳过：{e}")
