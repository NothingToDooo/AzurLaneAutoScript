"""基于 pywebio.platform.fastapi 精简出的本地 WebUI 服务。"""

import asyncio
import functools
import inspect
import mimetypes
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import uvicorn
from pywebio import session as pywebio_session
from pywebio import utils as pywebio_utils
from pywebio.platform import page as pywebio_page
from pywebio.platform.fastapi import (
    STATIC_PATH,
    Session,
    cdn_validation,
    get_free_port,
    open_webbrowser_on_server_started,
    webio_routes,
)
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse
from starlette.routing import Mount
from starlette.staticfiles import NotModifiedResponse, StaticFiles


class HeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _iscoroutinefunction(obj):
    while isinstance(obj, functools.partial):
        obj = obj.func
    return inspect.iscoroutinefunction(obj)


def _patch_pywebio_coroutine_checker() -> None:
    # pywebio 在导入时缓存了旧协程判断函数，统一收口到 WebUI 依赖边界。
    pywebio_utils.iscoroutinefunction = _iscoroutinefunction
    pywebio_page.iscoroutinefunction = _iscoroutinefunction
    pywebio_session.iscoroutinefunction = _iscoroutinefunction


_patch_pywebio_coroutine_checker()


@dataclass(slots=True)
class AsgiAppOptions:
    cdn: object = True
    static_dir: object = None
    debug: bool = False
    allowed_origins: object = None
    check_origin: object = None


@dataclass(slots=True)
class ServerOptions:
    port: int = 0
    host: str = ""
    auto_open_webbrowser: bool = False
    asgi_options: AsgiAppOptions = field(default_factory=AsgiAppOptions)


class LocalStaticFiles(StaticFiles):
    _mimetypes = mimetypes.MimeTypes(filenames=())

    def file_response(self, full_path, stat_result, scope, status_code=200):
        request_headers = Headers(scope=scope)
        media_type = self._mimetypes.guess_type(os.fspath(full_path))[0] or "application/octet-stream"
        response = FileResponse(full_path, status_code=status_code, stat_result=stat_result, media_type=media_type)
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response


async def _run_lifespan_callbacks(callbacks):
    for callback in callbacks or []:
        result = callback()
        if inspect.isawaitable(result):
            await result


def _build_lifespan(starlette_settings):
    on_startup = starlette_settings.pop("on_startup", None)
    on_shutdown = starlette_settings.pop("on_shutdown", None)
    lifespan = starlette_settings.pop("lifespan", None)
    if lifespan is not None:
        if on_startup or on_shutdown:
            raise ValueError("lifespan 不能和 on_startup/on_shutdown 同时使用。")
        return lifespan
    if not on_startup and not on_shutdown:
        return None

    @asynccontextmanager
    async def lifespan_context(_app):
        await _run_lifespan_callbacks(on_startup)
        try:
            yield
        finally:
            await _run_lifespan_callbacks(on_shutdown)

    return lifespan_context


def _asgi_options_from_settings(options, settings):
    if options is not None:
        return options
    return AsgiAppOptions(
        cdn=settings.pop("cdn", True),
        static_dir=settings.pop("static_dir", None),
        debug=settings.pop("debug", False),
        allowed_origins=settings.pop("allowed_origins", None),
        check_origin=settings.pop("check_origin", None),
    )


def asgi_app(applications, options=None, **starlette_settings):
    options = _asgi_options_from_settings(options, starlette_settings)
    debug = Session.debug = os.environ.get("PYWEBIO_DEBUG", options.debug)
    cdn = cdn_validation(options.cdn, "warn")
    if cdn is False:
        cdn = "pywebio_static"
    routes = webio_routes(
        applications,
        cdn=cdn,
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
    lifespan = _build_lifespan(starlette_settings)
    return Starlette(routes=routes, middleware=middleware, debug=debug, lifespan=lifespan, **starlette_settings)


def _server_options_from_settings(options, settings):
    if options is not None:
        return options
    return ServerOptions(
        port=settings.pop("port", 0),
        host=settings.pop("host", ""),
        auto_open_webbrowser=settings.pop("auto_open_webbrowser", False),
        asgi_options=AsgiAppOptions(
            cdn=settings.pop("cdn", True),
            static_dir=settings.pop("static_dir", None),
            debug=settings.pop("debug", False),
            allowed_origins=settings.pop("allowed_origins", None),
            check_origin=settings.pop("check_origin", None),
        ),
    )


def start_server(applications, options=None, **uvicorn_settings):
    options = _server_options_from_settings(options, uvicorn_settings)
    app = asgi_app(applications, options=options.asgi_options)

    if options.auto_open_webbrowser:
        asyncio.get_event_loop().create_task(open_webbrowser_on_server_started("localhost", options.port))

    host = options.host or "127.0.0.1"
    port = options.port

    if port == 0:
        port = get_free_port()

    uvicorn_settings.setdefault("log_config", None)
    uvicorn.run(app, host=host, port=port, **uvicorn_settings)
