import asyncio
import mimetypes
import warnings
from typing import TYPE_CHECKING

from module.webui.fastapi import AsgiAppOptions, LocalStaticFiles, asgi_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_local_static_files_uses_builtin_mime_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / "app.js"
    file.write_text("console.log(1);", encoding="utf-8")
    monkeypatch.setattr(mimetypes, "guess_type", lambda *_args, **_kwargs: ("application/x-broken", None))

    response = LocalStaticFiles(directory=tmp_path).file_response(file, file.stat(), {"type": "http", "headers": []})

    assert response.headers["content-type"] == "text/javascript; charset=utf-8"


def test_asgi_app_runs_legacy_lifespan_callbacks() -> None:
    events = []

    def index() -> None:
        return None

    async def exercise() -> None:
        app = asgi_app(
            applications=[index],
            on_startup=[lambda: events.append("start")],
            on_shutdown=[lambda: events.append("stop")],
        )

        async with app.router.lifespan_context(app):
            assert events == ["start"]

        assert events == ["start", "stop"]

    asyncio.run(exercise())


def test_asgi_app_accepts_options_object() -> None:
    def index() -> None:
        return None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        app = asgi_app([index], options=AsgiAppOptions(debug=True))

    assert app.debug is True
    deprecation_warnings = [item.message for item in caught if issubclass(item.category, DeprecationWarning)]
    assert deprecation_warnings == []
