import argparse
import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.bootstrap import InstanceProcessExitKind, build_default_instance_process_host
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import FrameType


EXIT_RESTART_REQUESTED = 75
EXIT_STOPPED = 130


class _ProcessStopSignal:
    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self, _signum: int, _frame: FrameType | None) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the typed ALAS instance runtime")
    parser.add_argument("command", nargs="?", default="alas", help="alas or a direct task command")
    parser.add_argument("--instance", default="alas", help="configuration instance name")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="ALAS source-tree root",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stop = _ProcessStopSignal()
    previous: dict[signal.Signals, object] = {}
    supported = tuple(
        item for item in (signal.SIGINT, getattr(signal, "SIGTERM", None)) if isinstance(item, signal.Signals)
    )
    for item in supported:
        previous[item] = signal.getsignal(item)
        signal.signal(item, stop.request)
    try:
        host = build_default_instance_process_host(args.project_root)
        exit_ = host.execute(args.instance, args.command, stop_signal=stop)
    finally:
        for item, handler in previous.items():
            signal.signal(
                item,
                cast("Callable[[int, FrameType | None], object] | int | None", handler),
            )

    if exit_.kind is InstanceProcessExitKind.FINISHED:
        return 0
    if exit_.kind is InstanceProcessExitKind.RESTART_REQUESTED:
        return EXIT_RESTART_REQUESTED
    if exit_.kind is InstanceProcessExitKind.STOPPED:
        return EXIT_STOPPED
    logger.error(f"Instance {args.instance!r} failed while executing {args.command!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
