import asyncio
import mimetypes

from module.webui.fastapi import LocalStaticFiles, asgi_app


def test_local_static_files_uses_builtin_mime_table(tmp_path, monkeypatch):
    file = tmp_path / "app.js"
    file.write_text("console.log(1);", encoding="utf-8")
    monkeypatch.setattr(mimetypes, "guess_type", lambda *_args, **_kwargs: ("application/x-broken", None))

    response = LocalStaticFiles(directory=tmp_path).file_response(file, file.stat(), {"type": "http", "headers": []})

    assert response.headers["content-type"] == "text/javascript; charset=utf-8"


def test_asgi_app_runs_legacy_lifespan_callbacks():
    events = []

    def index():
        return None

    async def exercise():
        app = asgi_app(
            applications=[index],
            on_startup=[lambda: events.append("start")],
            on_shutdown=[lambda: events.append("stop")],
        )

        async with app.router.lifespan_context(app):
            assert events == ["start"]

        assert events == ["start", "stop"]

    asyncio.run(exercise())
