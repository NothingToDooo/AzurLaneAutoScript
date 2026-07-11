import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
from PIL import Image

from module.base.atomic import atomic_replace, file_write, folder_rmtree, to_tmp_file
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.ocr.result import RecognitionResult

type _EncodedBundle = tuple[bytes, bytes, bytes]


@dataclass(slots=True)
class _ProcessSampleBudget:
    new_samples: int = 0


_PROCESS_SAMPLE_BUDGET = _ProcessSampleBudget()
_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "captured_at",
        "digest",
        "raw_text",
        "normalized_text",
        "score",
        "value",
        "valid",
        "reason",
        "latency_seconds",
        "profile",
        "model",
        "area",
        "alphabet",
        "letter",
        "threshold",
        "expected_total",
        "raw_shape",
        "raw_dtype",
        "processed_shape",
        "processed_dtype",
    }
)
_PROFILE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _is_valid_profile(profile: str) -> bool:
    return _PROFILE_PATTERN.fullmatch(profile) is not None and profile not in {".", ".."}


class OcrFailureRecordStatus(StrEnum):
    SAVED = "saved"
    DUPLICATE = "duplicate"
    LIMIT_REACHED = "limit_reached"
    TOO_LARGE = "too_large"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class OcrFailureRecordResult:
    status: OcrFailureRecordStatus
    digest: str
    directory: Path | None


class OcrFailureRecorder(Protocol):
    def record[T](  # noqa: PLR0913
        self,
        result: RecognitionResult[T],
        *,
        raw_image: np.ndarray,
        processed_image: np.ndarray,
        area: tuple[int, int, int, int] | None,
        alphabet: str | None,
        letter: tuple[int, int, int],
        threshold: int,
        expected_total: int | None = None,
    ) -> OcrFailureRecordResult: ...


class OcrFailureStore:
    def __init__(
        self,
        root: Path = Path("./log/ocr_failure"),
        *,
        max_total_samples: int = 256,
        max_samples_per_profile: int = 64,
        max_total_bytes: int = 64 * 1024 * 1024,
        max_new_samples_per_process: int = 16,
    ) -> None:
        self._root = root
        self._max_total_samples = max_total_samples
        self._max_samples_per_profile = max_samples_per_profile
        self._max_total_bytes = max_total_bytes
        self._max_new_samples_per_process = max_new_samples_per_process
        self._disabled = False

    def record[T](  # noqa: PLR0913
        self,
        result: RecognitionResult[T],
        *,
        raw_image: np.ndarray,
        processed_image: np.ndarray,
        area: tuple[int, int, int, int] | None,
        alphabet: str | None,
        letter: tuple[int, int, int],
        threshold: int,
        expected_total: int | None = None,
    ) -> OcrFailureRecordResult:
        if self._disabled:
            return OcrFailureRecordResult(OcrFailureRecordStatus.DISABLED, "", None)
        try:
            return self._record(
                result,
                raw_image=raw_image,
                processed_image=processed_image,
                area=area,
                alphabet=alphabet,
                letter=letter,
                threshold=threshold,
                expected_total=expected_total,
            )
        except OSError as error:
            self._disabled = True
            logger.warning("OCR failure store disabled after an unrecoverable OSError: %s", error)
            return OcrFailureRecordResult(OcrFailureRecordStatus.DISABLED, "", None)

    def _record[T](  # noqa: PLR0913
        self,
        result: RecognitionResult[T],
        *,
        raw_image: np.ndarray,
        processed_image: np.ndarray,
        area: tuple[int, int, int, int] | None,
        alphabet: str | None,
        letter: tuple[int, int, int],
        threshold: int,
        expected_total: int | None = None,
    ) -> OcrFailureRecordResult:
        self._validate_result(result)
        self._validate_images(raw_image, processed_image)
        digest = self._digest(
            result,
            processed_image=processed_image,
            area=area,
            alphabet=alphabet,
            letter=letter,
            threshold=threshold,
            expected_total=expected_total,
        )
        final_directory = self._root / result.profile / digest
        if self._is_complete_bundle(final_directory):
            return OcrFailureRecordResult(OcrFailureRecordStatus.DUPLICATE, digest, final_directory)
        existing_bundles = list(self._iter_complete_bundles())
        profile_directory = self._root / result.profile
        if self._sample_limit_reached(profile_directory, existing_bundles):
            return OcrFailureRecordResult(OcrFailureRecordStatus.LIMIT_REACHED, digest, None)

        bundle = self._encode_bundle(
            result,
            digest=digest,
            raw_image=raw_image,
            processed_image=processed_image,
            area=area,
            alphabet=alphabet,
            letter=letter,
            threshold=threshold,
            expected_total=expected_total,
        )
        bundle_size = sum(len(content) for content in bundle)
        if bundle_size > self._max_total_bytes:
            return OcrFailureRecordResult(OcrFailureRecordStatus.TOO_LARGE, digest, None)
        existing_size = sum(self._bundle_disk_size(directory) for directory in existing_bundles)
        if existing_size + bundle_size > self._max_total_bytes:
            return OcrFailureRecordResult(OcrFailureRecordStatus.LIMIT_REACHED, digest, None)

        if not self._publish_bundle(final_directory, bundle):
            return OcrFailureRecordResult(OcrFailureRecordStatus.DUPLICATE, digest, final_directory)
        _PROCESS_SAMPLE_BUDGET.new_samples += 1
        return OcrFailureRecordResult(OcrFailureRecordStatus.SAVED, digest, final_directory)

    @staticmethod
    def _validate_result[T](result: RecognitionResult[T]) -> None:
        if result.valid:
            message = "OCR failure store accepts only failed recognition results"
            raise ValueError(message)
        if not _is_valid_profile(result.profile):
            message = "profile must use 1-64 ASCII letters, digits, underscores, dots, or hyphens without traversal"
            raise ValueError(message)

    @staticmethod
    def _encode_bundle[T](  # noqa: PLR0913
        result: RecognitionResult[T],
        *,
        digest: str,
        raw_image: np.ndarray,
        processed_image: np.ndarray,
        area: tuple[int, int, int, int] | None,
        alphabet: str | None,
        letter: tuple[int, int, int],
        threshold: int,
        expected_total: int | None,
    ) -> _EncodedBundle:
        metadata = {
            "schema_version": 1,
            "captured_at": datetime.now().astimezone().isoformat(),
            "digest": digest,
            "raw_text": result.raw_text,
            "normalized_text": result.normalized_text,
            "score": result.score,
            "value": result.value,
            "valid": result.valid,
            "reason": result.reason.value if result.reason is not None else None,
            "latency_seconds": result.latency_seconds,
            "profile": result.profile,
            "model": result.model,
            "area": list(area) if area is not None else None,
            "alphabet": alphabet,
            "letter": list(letter),
            "threshold": threshold,
            "expected_total": expected_total,
            "raw_shape": list(raw_image.shape),
            "raw_dtype": str(raw_image.dtype),
            "processed_shape": list(processed_image.shape),
            "processed_dtype": str(processed_image.dtype),
        }
        raw_png = OcrFailureStore._png_bytes(raw_image)
        processed_png = OcrFailureStore._png_bytes(processed_image)
        metadata_json = (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        return raw_png, processed_png, metadata_json

    def _sample_limit_reached(self, profile_directory: Path, existing_bundles: list[Path]) -> bool:
        profile_samples = sum(bundle.parent == profile_directory for bundle in existing_bundles)
        # 所有 store 共享进程计数，每个实例用自己的配置上限解释该计数。
        return (
            _PROCESS_SAMPLE_BUDGET.new_samples >= self._max_new_samples_per_process
            or len(existing_bundles) >= self._max_total_samples
            or profile_samples >= self._max_samples_per_profile
        )

    def _publish_bundle(self, final_directory: Path, bundle: _EncodedBundle) -> bool:
        temp_directory = Path(to_tmp_file(final_directory))
        raw_png, processed_png, metadata_json = bundle
        try:
            file_write(temp_directory / "raw.png", raw_png)
            file_write(temp_directory / "processed.png", processed_png)
            file_write(temp_directory / "metadata.json", metadata_json)
            atomic_replace(temp_directory, final_directory)
        except OSError:
            folder_rmtree(temp_directory)
            if self._is_complete_bundle(final_directory):
                return False
            raise
        return True

    @staticmethod
    def _png_bytes(image: np.ndarray) -> bytes:
        buffer = BytesIO()
        Image.fromarray(image).save(buffer, format="PNG")
        return buffer.getvalue()

    @staticmethod
    def _validate_images(raw_image: np.ndarray, processed_image: np.ndarray) -> None:
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
    def _digest[T](  # noqa: PLR0913
        result: RecognitionResult[T],
        *,
        processed_image: np.ndarray,
        area: tuple[int, int, int, int] | None,
        alphabet: str | None,
        letter: tuple[int, int, int],
        threshold: int,
        expected_total: int | None,
    ) -> str:
        context = {
            "schema_version": 1,
            "profile": result.profile,
            "model": result.model,
            "reason": result.reason.value if result.reason is not None else None,
            "raw_text": result.raw_text,
            "normalized_text": result.normalized_text,
            "area": area,
            "alphabet": alphabet,
            "letter": letter,
            "threshold": threshold,
            "expected_total": expected_total,
            "processed_dtype": str(processed_image.dtype),
            "processed_shape": processed_image.shape,
        }
        canonical_context = json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        hasher = hashlib.sha256(canonical_context)
        hasher.update(np.ascontiguousarray(processed_image).tobytes())
        return hasher.hexdigest()

    @staticmethod
    def _is_complete_bundle(directory: Path) -> bool:
        if not all((directory / name).is_file() for name in ("raw.png", "processed.png", "metadata.json")):
            return False
        try:
            metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError, UnicodeDecodeError:
            return False
        return (
            isinstance(metadata, dict)
            and metadata.keys() >= _METADATA_FIELDS
            and metadata.get("schema_version") == 1
            and metadata.get("digest") == directory.name
            and metadata.get("profile") == directory.parent.name
        )

    @staticmethod
    def _bundle_disk_size(directory: Path) -> int:
        return sum((directory / name).stat().st_size for name in ("raw.png", "processed.png", "metadata.json"))

    def _iter_complete_bundles(self) -> Iterator[Path]:
        if not self._root.is_dir():
            return
        for profile_directory in self._root.iterdir():
            if not profile_directory.is_dir() or not _is_valid_profile(profile_directory.name):
                continue
            for bundle_directory in profile_directory.iterdir():
                if not re.fullmatch(r"[0-9a-f]{64}", bundle_directory.name):
                    continue
                if self._is_complete_bundle(bundle_directory):
                    yield bundle_directory


OCR_FAILURE_STORE = OcrFailureStore()
