from importlib import import_module
from threading import RLock
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence

    from module.base.type_alias import ImageArray
    from module.ocr.result import RawOcrResult


_MODEL_NAME = "densenet_lite_136-gru"


class _OcrSession(Protocol):
    def ensure_loaded(self) -> None: ...

    def atomic_ocr_for_single_lines_raw(
        self,
        img_list: Sequence[ImageArray],
        cand_alphabet: Collection[str] | str | None = None,
    ) -> list[RawOcrResult]: ...


def _create_al_ocr() -> _OcrSession:
    al_ocr_class = import_module("module.ocr.al_ocr").AlOcr
    return cast("_OcrSession", al_ocr_class(model_name=_MODEL_NAME))


class OcrRuntime:
    def __init__(self, factory: Callable[[], _OcrSession] = _create_al_ocr) -> None:
        self._factory = factory
        self._lock = RLock()
        self._session: _OcrSession | None = None

    @property
    def model_name(self) -> str:
        return _MODEL_NAME

    def atomic_ocr_for_single_lines_raw(
        self,
        img_list: Sequence[ImageArray],
        cand_alphabet: Collection[str] | str | None = None,
    ) -> list[RawOcrResult]:
        with self._lock:
            session = self._session
            if session is None:
                session = self._factory()
                session.ensure_loaded()
                self._session = session
            return session.atomic_ocr_for_single_lines_raw(img_list, cand_alphabet=cand_alphabet)

    def release(self) -> None:
        with self._lock:
            self._session = None


class OcrModel:
    def __init__(self, factory: Callable[[], _OcrSession] = _create_al_ocr) -> None:
        self._runtime = OcrRuntime(factory)

    @property
    def azur_lane(self) -> OcrRuntime:
        return self._runtime

    @property
    def cnocr(self) -> OcrRuntime:
        return self._runtime

    def release(self) -> None:
        self._runtime.release()


OCR_MODEL = OcrModel()
