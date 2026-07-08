import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from functools import partial, wraps
from importlib.util import find_spec

from module.logger import logger
from module.webui.setting import cached_class_property


class CachedThreadPoolExecutor:
    @cached_class_property
    def executor(cls):
        pool = ThreadPoolExecutor(max_workers=5)
        logger.info("Patched ThreadPoolExecutor created")
        return pool


def get_or_create_event_loop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def wrap(func):
    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = get_or_create_event_loop()
        if executor is None:
            executor = CachedThreadPoolExecutor.executor
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, pfunc)

    return run


def patch_executor():
    """
    限制 loop.run_in_executor 的线程池大小，避免静态文件服务创建过多线程。
    """
    if find_spec("aiofiles") is None:
        return

    loop = get_or_create_event_loop()
    loop.set_default_executor(CachedThreadPoolExecutor.executor)
