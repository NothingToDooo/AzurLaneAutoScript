import argparse
import signal
import sys
import threading
from typing import TYPE_CHECKING, cast

from module.bootstrap.production import run_default_command
from module.logger import logger
from module.runtime.runner import CommandStatus

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
    parser = argparse.ArgumentParser(description="Run the personal ALAS runtime")
    parser.add_argument("command", nargs="?", default="alas", help="alas or one task command")
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
        outcome = run_default_command(
            args.command,
            stop_signal=stop,
        )
    finally:
        for item, handler in previous.items():
            signal.signal(
                item,
                cast("Callable[[int, FrameType | None], object] | int | None", handler),
            )

    if outcome.status is CommandStatus.FINISHED:
        return 0
    if outcome.status is CommandStatus.RESTART_REQUESTED:
        return EXIT_RESTART_REQUESTED
    if outcome.status is CommandStatus.STOPPED:
        return EXIT_STOPPED
    logger.error(f"Command {args.command!r} failed: {outcome.message or outcome.status.value}")
    if outcome.error_bundle is not None:
        logger.error(f"Error bundle: {outcome.error_bundle}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
