"""基于 pywebio.platform.fastapi 精简出的本地 WebUI 服务。"""

import asyncio
import os

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
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles


class HeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response


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
        routes.append(Mount("/static", app=StaticFiles(directory=static_dir), name="static"))
    routes.append(
        Mount(
            "/pywebio_static",
            app=StaticFiles(directory=STATIC_PATH),
            name="pywebio_static",
        )
    )
    middleware = [Middleware(HeaderMiddleware)]
    return Starlette(routes=routes, middleware=middleware, debug=debug, **starlette_settings)


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

    uvicorn.run(app, host=host, port=port, **uvicorn_settings)
