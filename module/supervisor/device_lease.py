import errno
import hashlib
import json
import os
import threading
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if os.name == "nt":
    import msvcrt
else:
    import fcntl

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import BinaryIO


UNKNOWN_DEVICE_LEASE_OWNER = "<unknown owner>"
_LOCK_BYTE_COUNT = 1
_METADATA_OFFSET = _LOCK_BYTE_COUNT
_MAX_METADATA_BYTES = 16 * 1024
_CONFLICT_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK})


def _require_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must not be empty or contain whitespace"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class DeviceLease:
    serial: str
    owner: str
    token: str

    def __post_init__(self) -> None:
        _require_identifier(self.serial, field_name="serial")
        _require_identifier(self.owner, field_name="owner")
        _require_identifier(self.token, field_name="token")


class DeviceLeaseConflictError(RuntimeError):
    def __init__(self, *, serial: str, requested_by: str, held_by: str) -> None:
        self.serial = serial
        self.requested_by = requested_by
        self.held_by = held_by
        super().__init__(f"device {serial} is already leased by {held_by}; requested by {requested_by}")


class InvalidDeviceLeaseError(RuntimeError):
    """lease 已释放、被伪造，或已被同一 serial 的后来 lease 替代。"""


@dataclass(frozen=True, slots=True)
class _HeldLease:
    lease: DeviceLease
    handle: BinaryIO


class DeviceLeaseRegistry:
    """以 OS 文件锁串行化同一设备，进程退出时由内核自动释放。"""

    __slots__ = ("_leases", "_lock", "_lock_root", "_token_factory")

    def __init__(
        self,
        lock_root: str | os.PathLike[str],
        *,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        root = Path(lock_root)
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        if not root.is_dir():
            message = f"device lease lock root is not a directory: {root}"
            raise NotADirectoryError(message)

        self._leases: dict[str, _HeldLease] = {}
        self._lock = threading.Lock()
        self._lock_root = root
        self._token_factory = _default_token if token_factory is None else token_factory

    def acquire(self, serial: str, owner: str) -> DeviceLease:
        _require_identifier(serial, field_name="serial")
        _require_identifier(owner, field_name="owner")

        with self._lock:
            current = self._leases.get(serial)
            if current is not None:
                raise DeviceLeaseConflictError(serial=serial, requested_by=owner, held_by=current.lease.owner)

            lease = DeviceLease(serial=serial, owner=owner, token=self._token_factory())
            path = self._lock_path(serial)
            handle = _open_lock_file(path)
            try:
                acquired = _try_lock_file(handle)
            except BaseException:
                handle.close()
                raise

            if not acquired:
                try:
                    held_by = _read_owner_metadata(handle)
                finally:
                    handle.close()
                raise DeviceLeaseConflictError(serial=serial, requested_by=owner, held_by=held_by)

            held = _HeldLease(lease=lease, handle=handle)
            try:
                with suppress(OSError):
                    _write_owner_metadata(handle, lease)
                self._leases[serial] = held
            except BaseException:
                try:
                    _unlock_file(handle)
                finally:
                    handle.close()
                raise
            return lease

    def release(self, lease: DeviceLease) -> None:
        if not isinstance(lease, DeviceLease):
            message = "lease must be a DeviceLease"
            raise TypeError(message)

        with self._lock:
            current = self._leases.get(lease.serial)
            if current is None or current.lease is not lease:
                message = f"device lease is not current: {lease.serial}/{lease.owner}"
                raise InvalidDeviceLeaseError(message)

            try:
                with suppress(OSError):
                    _clear_owner_metadata(current.handle)
                _unlock_file(current.handle)
            finally:
                try:
                    current.handle.close()
                finally:
                    del self._leases[lease.serial]

    def holder(self, serial: str) -> str | None:
        _require_identifier(serial, field_name="serial")
        with self._lock:
            current = self._leases.get(serial)
            if current is not None:
                return current.lease.owner

            handle = _open_lock_file(self._lock_path(serial))
            try:
                if not _try_lock_file(handle):
                    return _read_owner_metadata(handle)
                try:
                    return None
                finally:
                    _unlock_file(handle)
            finally:
                handle.close()

    def active_leases(self) -> tuple[DeviceLease, ...]:
        """返回当前 registry 进程内持有的 lease；不会枚举其他进程。"""

        with self._lock:
            return tuple(sorted((held.lease for held in self._leases.values()), key=lambda lease: lease.serial))

    def _lock_path(self, serial: str) -> Path:
        digest = hashlib.sha256(serial.encode("utf-8")).hexdigest()
        path = self._lock_root / f"{digest}.lock"
        if path.parent != self._lock_root:
            message = "device lease path escaped the configured lock root"
            raise ValueError(message)
        return path


def _open_lock_file(path: Path) -> BinaryIO:
    if path.is_symlink():
        message = f"device lease lock file must not be a symbolic link: {path}"
        raise OSError(message)

    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return os.fdopen(descriptor, "r+b", buffering=0)
    except BaseException:
        os.close(descriptor)
        raise


def _try_lock_file(handle: BinaryIO) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTE_COUNT)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _CONFLICT_ERRNOS:
            return False
        raise
    return True


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTE_COUNT)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_owner_metadata(handle: BinaryIO, lease: DeviceLease) -> None:
    metadata = json.dumps(
        {"schema": 1, "owner": lease.owner, "pid": os.getpid()},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    handle.seek(_METADATA_OFFSET)
    handle.truncate(_METADATA_OFFSET)
    handle.write(metadata)
    handle.flush()
    os.fsync(handle.fileno())


def _clear_owner_metadata(handle: BinaryIO) -> None:
    handle.seek(_METADATA_OFFSET)
    handle.truncate(_METADATA_OFFSET)
    handle.flush()
    os.fsync(handle.fileno())


def _read_owner_metadata(handle: BinaryIO) -> str:
    try:
        handle.seek(_METADATA_OFFSET)
        payload = handle.read(_MAX_METADATA_BYTES + 1)
        if not payload or len(payload) > _MAX_METADATA_BYTES:
            return UNKNOWN_DEVICE_LEASE_OWNER
        metadata: object = json.loads(payload.decode("utf-8"))
        if not isinstance(metadata, dict) or metadata.get("schema") != 1:
            return UNKNOWN_DEVICE_LEASE_OWNER
        owner = metadata.get("owner")
        if not isinstance(owner, str):
            return UNKNOWN_DEVICE_LEASE_OWNER
        _require_identifier(owner, field_name="metadata owner")
    except OSError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError:
        return UNKNOWN_DEVICE_LEASE_OWNER
    return owner


def _default_token() -> str:
    return uuid.uuid4().hex
