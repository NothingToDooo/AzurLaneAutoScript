import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Protocol

import numpy as np
from PIL import Image

from module.base.atomic import atomic_replace, file_write, folder_rmtree, to_tmp_file

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.ocr.result import RecognitionResult

type _RecognitionResult[T] = RecognitionResult[T]
type _PathIterator = Iterator[Path]
type _EncodedBundle = tuple[bytes, bytes, bytes]


@dataclass(slots=True)
class _ProcessSampleBudget:
    new_samples: int = 0


_PROCESS_SAMPLE_BUDGET = _ProcessSampleBudget()
_STORE_LOCK = Lock()
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
    return (
        _PROFILE_PATTERN.fullmatch(profile) is not None
        and profile not in {".", ".."}
        and not os.path.isreserved(profile)
    )


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink() or path.is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError, FileNotFoundError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


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
        result: _RecognitionResult[T],
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
    """将失败样本写入调用方信任的本地目录；root 可以是 junction。"""

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
        result: _RecognitionResult[T],
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
        except OSError:
            self._disabled = True
            raise

    def _record[T](  # noqa: PLR0913
        self,
        result: _RecognitionResult[T],
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
        with _STORE_LOCK:
            if self._disabled:
                return OcrFailureRecordResult(OcrFailureRecordStatus.DISABLED, "", None)
            try:
                record_result, _ = self._check_sample_limits(final_directory, digest)
            except OSError:
                self._disabled = True
                raise
        if record_result is not None:
            return record_result

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

        with _STORE_LOCK:
            if self._disabled:
                return OcrFailureRecordResult(OcrFailureRecordStatus.DISABLED, "", None)
            try:
                return self._publish_within_limits(final_directory, digest, bundle)
            except OSError:
                self._disabled = True
                raise

    def _check_sample_limits(
        self,
        final_directory: Path,
        digest: str,
    ) -> tuple[OcrFailureRecordResult | None, list[Path]]:
        if self._is_complete_bundle(final_directory):
            result = OcrFailureRecordResult(OcrFailureRecordStatus.DUPLICATE, digest, final_directory)
            return result, []
        existing_bundles = list(self._iter_complete_bundles())
        if self._sample_limit_reached(final_directory.parent, existing_bundles):
            result = OcrFailureRecordResult(OcrFailureRecordStatus.LIMIT_REACHED, digest, None)
            return result, existing_bundles
        return None, existing_bundles

    def _publish_within_limits(
        self,
        final_directory: Path,
        digest: str,
        bundle: _EncodedBundle,
    ) -> OcrFailureRecordResult:
        record_result, existing_bundles = self._check_sample_limits(final_directory, digest)
        if record_result is not None:
            return record_result
        bundle_size = sum(len(content) for content in bundle)
        existing_size = sum(self._bundle_disk_size(directory) for directory in existing_bundles)
        if existing_size + bundle_size > self._max_total_bytes:
            return OcrFailureRecordResult(OcrFailureRecordStatus.LIMIT_REACHED, digest, None)
        if not self._publish_bundle(final_directory, bundle):
            return OcrFailureRecordResult(OcrFailureRecordStatus.DUPLICATE, digest, final_directory)
        _PROCESS_SAMPLE_BUDGET.new_samples += 1
        return OcrFailureRecordResult(OcrFailureRecordStatus.SAVED, digest, final_directory)

    @staticmethod
    def _validate_result[T](result: _RecognitionResult[T]) -> None:
        if result.valid:
            message = "OCR failure store accepts only failed recognition results"
            raise ValueError(message)
        if not _is_valid_profile(result.profile):
            message = "profile must use 1-64 ASCII letters, digits, underscores, dots, or hyphens without traversal"
            raise ValueError(message)

    @staticmethod
    def _encode_bundle[T](  # noqa: PLR0913
        result: _RecognitionResult[T],
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
        self._validate_temp_path(temp_directory)
        if temp_directory.exists():
            message = "temporary OCR failure path must not already exist"
            raise ValueError(message)
        raw_png, processed_png, metadata_json = bundle
        try:
            file_write(temp_directory / "raw.png", raw_png)
            file_write(temp_directory / "processed.png", processed_png)
            file_write(temp_directory / "metadata.json", metadata_json)
            self._validate_temp_path(temp_directory)
            atomic_replace(temp_directory, final_directory)
        except ValueError:
            self._cleanup_temp_directory(temp_directory)
            raise
        except OSError:
            self._cleanup_temp_directory(temp_directory)
            if self._is_complete_bundle(final_directory):
                return False
            raise
        return True

    def _cleanup_temp_directory(self, temp_directory: Path) -> None:
        if not self._is_safe_temp_path(temp_directory):
            return
        folder_rmtree(temp_directory)

    def _validate_temp_path(self, path: Path) -> None:
        if not self._is_safe_temp_path(path):
            message = "temporary OCR failure path must contain no reparse points below its root"
            raise ValueError(message)

    def _is_safe_temp_path(self, path: Path) -> bool:
        """root 本身受信任；这里只避免递归清理沿子级 reparse point 误删。"""
        root_absolute = self._root.absolute()
        path_absolute = path.absolute()
        try:
            relative_path = path_absolute.relative_to(root_absolute)
        except ValueError:
            return False

        current = root_absolute
        for part in relative_path.parts:
            current /= part
            if _is_reparse_point(current):
                return False
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
        result: _RecognitionResult[T],
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

    def _iter_complete_bundles(self) -> _PathIterator:
        if not self._root.is_dir():
            return
        for profile_directory in self._root.iterdir():
            if not _is_valid_profile(profile_directory.name):
                continue
            if not profile_directory.is_dir():
                continue
            for bundle_directory in profile_directory.iterdir():
                if not re.fullmatch(r"[0-9a-f]{64}", bundle_directory.name):
                    continue
                if self._is_complete_bundle(bundle_directory):
                    yield bundle_directory


OCR_FAILURE_STORE = OcrFailureStore()
