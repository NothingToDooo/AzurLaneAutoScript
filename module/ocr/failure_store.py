import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
from PIL import Image

from module.base.atomic import atomic_remove, atomic_write
from module.logger import logger
from module.project_paths import PROJECT_ROOT

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.ocr.result import RecognitionResult

type _RecognitionResult[T] = RecognitionResult[T]
type _EncodedBundle = tuple[bytes, bytes, bytes]

_PROFILE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _is_valid_profile(profile: str) -> bool:
    return (
        _PROFILE_PATTERN.fullmatch(profile) is not None
        and profile not in {".", ".."}
        and not os.path.isreserved(profile)
    )


@dataclass(frozen=True, slots=True)
class OcrFailureSample[T]:
    result: _RecognitionResult[T]
    raw_image: ImageArray
    processed_image: ImageArray
    area: tuple[int, int, int, int] | None
    alphabet: str | None
    letter: tuple[int, int, int]
    threshold: int
    expected_total: int | None = None


class OcrFailureRecorder(Protocol):
    def record[T](self, sample: OcrFailureSample[T]) -> Path | None: ...


class OcrFailureStore:
    """每个 OCR profile 只保留最近一次失败快照。"""

    __slots__ = ("_root",)

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            message = "root must be a Path"
            raise TypeError(message)
        self._root = root

    def record[T](self, sample: OcrFailureSample[T]) -> Path | None:
        self._validate_result(sample.result)
        self._validate_images(sample.raw_image, sample.processed_image)
        directory = self._root / sample.result.profile
        try:
            bundle = self._encode_bundle(sample)
            self._publish_bundle(directory, bundle)
        except (OSError, TypeError, ValueError) as error:
            logger.warning(
                "OCR failure snapshot was not saved "
                f"profile={sample.result.profile!r} error_type={type(error).__name__!r}"
            )
            return None
        return directory

    @staticmethod
    def _validate_result[T](result: _RecognitionResult[T]) -> None:
        if result.valid:
            message = "OCR failure store accepts only failed recognition results"
            raise ValueError(message)
        if not _is_valid_profile(result.profile):
            message = "profile must use 1-64 ASCII letters, digits, underscores, dots, or hyphens without traversal"
            raise ValueError(message)

    @staticmethod
    def _validate_images(raw_image: ImageArray, processed_image: ImageArray) -> None:
        if not isinstance(raw_image, np.ndarray) or not isinstance(processed_image, np.ndarray):
            message = "raw and processed images must be NumPy arrays"
            raise TypeError(message)
        if raw_image.dtype != np.uint8 or processed_image.dtype != np.uint8:
            message = "raw and processed images must use uint8 dtype"
            raise ValueError(message)
        if raw_image.size == 0 or processed_image.size == 0:
            message = "raw and processed images must be non-empty"
            raise ValueError(message)
        is_valid_raw_shape = raw_image.ndim == 2 or (raw_image.ndim == 3 and raw_image.shape[2] == 3)
        if not is_valid_raw_shape:
            message = "raw image must be HxW or HxWx3"
            raise ValueError(message)
        if processed_image.ndim != 2:
            message = "processed image must be HxW"
            raise ValueError(message)

    @staticmethod
    def _encode_bundle[T](sample: OcrFailureSample[T]) -> _EncodedBundle:
        result = sample.result
        metadata = {
            "schema_version": 1,
            "captured_at": datetime.now().astimezone().isoformat(),
            "raw_text": result.raw_text,
            "normalized_text": result.normalized_text,
            "score": result.score,
            "value": result.value,
            "valid": result.valid,
            "reason": result.reason.value if result.reason is not None else None,
            "latency_seconds": result.latency_seconds,
            "profile": result.profile,
            "model": result.model,
            "area": list(sample.area) if sample.area is not None else None,
            "alphabet": sample.alphabet,
            "letter": list(sample.letter),
            "threshold": sample.threshold,
            "expected_total": sample.expected_total,
            "raw_shape": list(sample.raw_image.shape),
            "raw_dtype": str(sample.raw_image.dtype),
            "processed_shape": list(sample.processed_image.shape),
            "processed_dtype": str(sample.processed_image.dtype),
        }
        raw_png = OcrFailureStore._png_bytes(sample.raw_image)
        processed_png = OcrFailureStore._png_bytes(sample.processed_image)
        metadata_json = (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        return raw_png, processed_png, metadata_json

    @staticmethod
    def _publish_bundle(directory: Path, bundle: _EncodedBundle) -> None:
        raw_png, processed_png, metadata_json = bundle
        metadata_path = directory / "metadata.json"
        # metadata 是提交标记；缺少它时，调试工具不会把半写入目录当成完整快照。
        atomic_remove(metadata_path)
        atomic_write(directory / "raw.png", raw_png)
        atomic_write(directory / "processed.png", processed_png)
        atomic_write(metadata_path, metadata_json)

    @staticmethod
    def _png_bytes(image: ImageArray) -> bytes:
        buffer = BytesIO()
        Image.fromarray(image).save(buffer, format="PNG")
        return buffer.getvalue()


OCR_FAILURE_STORE = OcrFailureStore(PROJECT_ROOT / "log" / "ocr_failure")
