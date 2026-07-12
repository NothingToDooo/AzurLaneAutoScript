"""基于 pywebio.platform.fastapi 精简出的本地 WebUI 服务。"""

import functools
import inspect
import mimetypes
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pywebio import session as pywebio_session
from pywebio import utils as pywebio_utils
from pywebio.platform import page as pywebio_page
from pywebio.platform.fastapi import (
    STATIC_PATH,
    Session,
    webio_routes,
)
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import FileResponse, Response
from starlette.routing import Mount
from starlette.staticfiles import NotModifiedResponse, StaticFiles

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.types import Lifespan, Scope

type LifespanCallback = Callable[[], Awaitable[None] | None]
type WebIOApplication = Callable[[], None]


class HeaderMiddleware(BaseHTTPMiddleware):
    cache_control = "no-cache"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = self.cache_control
        return response


def _iscoroutinefunction(obj: object) -> bool:
    while isinstance(obj, functools.partial):
        obj = obj.func
    return inspect.iscoroutinefunction(obj)


def _patch_pywebio_coroutine_checker() -> None:
    # pywebio 在导入时缓存了旧协程判断函数，统一收口到 WebUI 依赖边界。
    vars(pywebio_utils)["iscoroutinefunction"] = _iscoroutinefunction
    vars(pywebio_page)["iscoroutinefunction"] = _iscoroutinefunction
    vars(pywebio_session)["iscoroutinefunction"] = _iscoroutinefunction


_patch_pywebio_coroutine_checker()

LIFESPAN_CALLBACKS_CONFLICT_MESSAGE = "lifespan 不能和 on_startup/on_shutdown 同时使用。"


@dataclass(slots=True)
class AsgiAppOptions:
    static_dir: str | os.PathLike[str] | None = None
    debug: bool = False
    allowed_origins: Sequence[str] | None = None
    check_origin: Callable[[str], bool] | None = None


class LocalStaticFiles(StaticFiles):
    _mimetypes = mimetypes.MimeTypes(filenames=())

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        request_headers = Headers(scope=scope)
        media_type = self._mimetypes.guess_type(os.fspath(full_path))[0] or "application/octet-stream"
        response = FileResponse(full_path, status_code=status_code, stat_result=stat_result, media_type=media_type)
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response


async def _run_lifespan_callbacks(callbacks: Sequence[LifespanCallback]) -> None:
    for callback in callbacks:
        result = callback()
        if inspect.isawaitable(result):
            await result


def _build_lifespan(
    on_startup: Sequence[LifespanCallback],
    on_shutdown: Sequence[LifespanCallback],
    lifespan: Lifespan[Starlette] | None,
) -> Lifespan[Starlette] | None:
    if lifespan is not None:
        if on_startup or on_shutdown:
            raise ValueError(LIFESPAN_CALLBACKS_CONFLICT_MESSAGE)
        return lifespan
    if not on_startup and not on_shutdown:
        return None

    @asynccontextmanager
    async def lifespan_context(_app: Starlette) -> AsyncIterator[None]:
        await _run_lifespan_callbacks(on_startup)
        try:
            yield
        finally:
            await _run_lifespan_callbacks(on_shutdown)

    return lifespan_context


def asgi_app(
    applications: list[WebIOApplication],
    options: AsgiAppOptions | None = None,
    *,
    on_startup: Sequence[LifespanCallback] = (),
    on_shutdown: Sequence[LifespanCallback] = (),
    lifespan: Lifespan[Starlette] | None = None,
) -> Starlette:
    if options is None:
        options = AsgiAppOptions()
    session_debug = os.environ.get("PYWEBIO_DEBUG")
    debug = options.debug if session_debug is None else bool(session_debug)
    Session.debug = debug
    routes = webio_routes(
        applications,
        cdn="pywebio_static",
        allowed_origins=options.allowed_origins,
        check_origin=options.check_origin,
    )
    if options.static_dir:
        routes.append(Mount("/static", app=LocalStaticFiles(directory=options.static_dir), name="static"))
    routes.append(
        Mount(
            "/pywebio_static",
            app=LocalStaticFiles(directory=STATIC_PATH),
            name="pywebio_static",
        )
    )
    middleware = [Middleware(HeaderMiddleware)]
    lifespan = _build_lifespan(on_startup, on_shutdown, lifespan)
    return Starlette(routes=routes, middleware=middleware, debug=debug, lifespan=lifespan)
