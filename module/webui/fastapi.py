"""基于 pywebio.platform.fastapi 精简出的本地 WebUI 服务。"""

import asyncio
import inspect
import mimetypes
import os
from contextlib import asynccontextmanager

import uvicorn
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


def asgi_app(
    applications, cdn=True, static_dir=None, debug=False, allowed_origins=None, check_origin=None, **starlette_settings
):
    debug = Session.debug = os.environ.get("PYWEBIO_DEBUG", debug)
    cdn = cdn_validation(cdn, "warn")
    if cdn is False:
        cdn = "pywebio_static"
    routes = webio_routes(
        applications,
        cdn=cdn,
        allowed_origins=allowed_origins,
        check_origin=check_origin,
    )
    if static_dir:
        routes.append(Mount("/static", app=LocalStaticFiles(directory=static_dir), name="static"))
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


def start_server(
    applications,
    port=0,
    host="",
    cdn=True,
    static_dir=None,
    debug=False,
    allowed_origins=None,
    check_origin=None,
    auto_open_webbrowser=False,
    **uvicorn_settings,
):

    app = asgi_app(
        applications,
        cdn=cdn,
        static_dir=static_dir,
        debug=debug,
        allowed_origins=allowed_origins,
        check_origin=check_origin,
    )

    if auto_open_webbrowser:
        asyncio.get_event_loop().create_task(open_webbrowser_on_server_started("localhost", port))

    if not host:
        host = "127.0.0.1"

    if port == 0:
        port = get_free_port()

    uvicorn_settings.setdefault("log_config", None)
    uvicorn.run(app, host=host, port=port, **uvicorn_settings)
