from urllib.parse import urlparse

from deploy.config import DeployConfig
from deploy.logger import logger
from deploy.utils import cached_property


class PipManager(DeployConfig):
    @cached_property
    def uv(self):
        return 'uv'

    @cached_property
    def uv_sync_args(self):
        args = ['--python', self.PythonVersion]
        if self.PypiMirror:
            args += ['--index-url', self.PypiMirror]
        if not self.SSLVerify:
            hosts = []
            if self.PypiMirror:
                host = urlparse(self.PypiMirror).hostname
                if host:
                    hosts.append(host)
            else:
                hosts += ['pypi.org', 'files.pythonhosted.org']
            for host in hosts:
                args += ['--allow-insecure-host', host]
        return ' '.join(args)

    def pip_install(self):
        logger.hr('Update Dependencies', 0)

        if not self.InstallDependencies:
            logger.info('InstallDependencies is disabled, skip')
            return

        logger.hr('Check Python', 1)
        self.execute(f'{self.uv} python install {self.PythonVersion}')

        logger.hr('Update Dependencies', 1)
        self.execute(f'{self.uv} sync {self.uv_sync_args}')
