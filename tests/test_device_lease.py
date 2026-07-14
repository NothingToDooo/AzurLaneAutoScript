import hashlib
from itertools import count
from multiprocessing import get_context
from threading import Barrier, Lock, Thread
from typing import TYPE_CHECKING, cast

import pytest

from module.supervisor import (
    DeviceLease,
    DeviceLeaseConflictError,
    DeviceLeaseRegistry,
    InvalidDeviceLeaseError,
)
from module.supervisor.device_lease import UNKNOWN_DEVICE_LEASE_OWNER

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess
    from multiprocessing.synchronize import Event as ProcessEvent
    from pathlib import Path


type _WorkerResult = tuple[str, str, str]


def _registry(lock_root: Path) -> DeviceLeaseRegistry:
    sequence = count(1)
    return DeviceLeaseRegistry(lock_root, token_factory=lambda: f"lease-{next(sequence)}")


def _race_for_lease(
    lock_root: str,
    owner: str,
    start: ProcessEvent,
    release: ProcessEvent,
    result: Connection,
) -> None:
    registry = DeviceLeaseRegistry(lock_root)
    start.wait()
    try:
        lease = registry.acquire("127.0.0.1:16384", owner)
    except DeviceLeaseConflictError as exc:
        result.send(("conflict", owner, exc.held_by))
    except Exception as exc:  # noqa: BLE001 - 子进程错误必须回传给父进程诊断。
        result.send(("error", owner, repr(exc)))
    else:
        result.send(("won", owner, ""))
        release.wait()
        registry.release(lease)
    finally:
        result.close()


def _hold_lease_until_terminated(lock_root: str, ready: ProcessEvent, hold: Connection) -> None:
    registry = DeviceLeaseRegistry(lock_root)
    registry.acquire("127.0.0.1:16384", "child-owner")
    ready.set()
    hold.recv()


def _stop_processes(processes: tuple[BaseProcess, ...], release: ProcessEvent) -> None:
    release.set()
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)


def test_only_one_owner_can_lease_a_serial(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = registry.acquire("127.0.0.1:16384", "account-a")

    with pytest.raises(DeviceLeaseConflictError, match="already leased") as caught:
        registry.acquire("127.0.0.1:16384", "account-b")

    assert caught.value.held_by == "account-a"
    assert registry.holder(first.serial) == "account-a"
    assert registry.active_leases() == (first,)
    registry.release(first)


def test_different_serials_have_independent_owners(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    first = registry.acquire("127.0.0.1:16384", "account-a")
    second = registry.acquire("127.0.0.1:16416", "account-b")

    assert registry.active_leases() == (first, second)
    registry.release(second)
    registry.release(first)


def test_stale_lease_cannot_release_a_later_owner(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    stale = registry.acquire("127.0.0.1:16384", "account-a")
    registry.release(stale)
    current = registry.acquire("127.0.0.1:16384", "account-b")

    with pytest.raises(InvalidDeviceLeaseError, match="not current"):
        registry.release(stale)

    assert registry.active_leases() == (current,)
    registry.release(current)


def test_same_value_forged_lease_cannot_release_current_owner(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    current = registry.acquire("127.0.0.1:16384", "account-a")
    forged = DeviceLease(serial=current.serial, owner=current.owner, token=current.token)

    with pytest.raises(InvalidDeviceLeaseError, match="not current"):
        registry.release(forged)

    assert registry.holder(current.serial) == current.owner
    registry.release(current)


def test_concurrent_threads_have_exactly_one_winner(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    barrier = Barrier(3)
    result_lock = Lock()
    winners: list[tuple[str, DeviceLease]] = []
    conflicts: list[str] = []

    def acquire(owner: str) -> None:
        barrier.wait()
        try:
            lease = registry.acquire("127.0.0.1:16384", owner)
        except DeviceLeaseConflictError:
            with result_lock:
                conflicts.append(owner)
        else:
            with result_lock:
                winners.append((owner, lease))

    threads = (Thread(target=acquire, args=("account-a",)), Thread(target=acquire, args=("account-b",)))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert len(winners) == 1
    assert len(conflicts) == 1
    assert winners[0][0] not in conflicts
    registry.release(winners[0][1])


def test_independent_registries_contend_through_the_os_lock(tmp_path: Path) -> None:
    first_registry = _registry(tmp_path)
    second_registry = _registry(tmp_path)
    first = first_registry.acquire("127.0.0.1:16384", "account-a")

    with pytest.raises(DeviceLeaseConflictError) as caught:
        second_registry.acquire(first.serial, "account-b")

    assert caught.value.held_by == first.owner
    first_registry.release(first)
    second = second_registry.acquire(first.serial, "account-b")
    second_registry.release(second)


def test_lock_path_is_a_digest_confined_to_the_injected_root(tmp_path: Path) -> None:
    serial = "../../outside:16384"
    registry = _registry(tmp_path)
    lease = registry.acquire(serial, "account-a")

    lock_files = tuple(tmp_path.glob("*.lock"))

    assert len(lock_files) == 1
    assert lock_files[0].name == f"{hashlib.sha256(serial.encode()).hexdigest()}.lock"
    assert serial not in lock_files[0].name
    assert lock_files[0].resolve().parent == tmp_path.resolve()
    registry.release(lease)
    assert serial.encode() not in lock_files[0].read_bytes()


def test_invalid_metadata_has_an_explicit_safe_fallback(tmp_path: Path) -> None:
    first_registry = _registry(tmp_path)
    second_registry = _registry(tmp_path)
    first = first_registry.acquire("127.0.0.1:16384", "account-a")
    (lock_file,) = tuple(tmp_path.glob("*.lock"))
    with lock_file.open("r+b") as stream:
        stream.seek(1)
        stream.truncate(1)

    with pytest.raises(DeviceLeaseConflictError) as caught:
        second_registry.acquire(first.serial, "account-b")

    assert caught.value.held_by == UNKNOWN_DEVICE_LEASE_OWNER
    first_registry.release(first)


def test_spawned_processes_have_exactly_one_winner(tmp_path: Path) -> None:
    context = get_context("spawn")
    start = context.Event()
    release = context.Event()
    receive_a, send_a = context.Pipe(duplex=False)
    receive_b, send_b = context.Pipe(duplex=False)
    processes = (
        context.Process(target=_race_for_lease, args=(str(tmp_path), "account-a", start, release, send_a)),
        context.Process(target=_race_for_lease, args=(str(tmp_path), "account-b", start, release, send_b)),
    )
    for process in processes:
        process.start()
    send_a.close()
    send_b.close()

    try:
        start.set()
        assert receive_a.poll(10)
        assert receive_b.poll(10)
        results = (
            cast("_WorkerResult", receive_a.recv()),
            cast("_WorkerResult", receive_b.recv()),
        )
        winners = [result for result in results if result[0] == "won"]
        conflicts = [result for result in results if result[0] == "conflict"]

        assert [result[0] for result in results].count("error") == 0
        assert len(winners) == 1
        assert len(conflicts) == 1
        assert conflicts[0][2] in {winners[0][1], UNKNOWN_DEVICE_LEASE_OWNER}
    finally:
        receive_a.close()
        receive_b.close()
        _stop_processes(processes, release)

    assert all(process.exitcode == 0 for process in processes)


def test_process_termination_releases_the_os_lock(tmp_path: Path) -> None:
    context = get_context("spawn")
    ready = context.Event()
    hold_receive, hold_send = context.Pipe(duplex=False)
    process = context.Process(target=_hold_lease_until_terminated, args=(str(tmp_path), ready, hold_receive))
    process.start()
    hold_receive.close()

    contender = _registry(tmp_path)
    try:
        assert ready.wait(timeout=10)
        with pytest.raises(DeviceLeaseConflictError) as caught:
            contender.acquire("127.0.0.1:16384", "parent-owner")
        assert caught.value.held_by == "child-owner"

        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()

        recovered = contender.acquire("127.0.0.1:16384", "parent-owner")
        contender.release(recovered)
    finally:
        hold_send.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
