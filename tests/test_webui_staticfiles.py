import mimetypes
from typing import TYPE_CHECKING

from module.webui.fastapi import LocalStaticFiles

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_local_static_files_uses_builtin_mime_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / "app.js"
    file.write_text("console.log(1);", encoding="utf-8")
    monkeypatch.setattr(mimetypes, "guess_type", lambda *_args, **_kwargs: ("application/x-broken", None))

    response = LocalStaticFiles(directory=tmp_path).file_response(file, file.stat(), {"type": "http", "headers": []})

    assert response.headers["content-type"] == "text/javascript; charset=utf-8"
