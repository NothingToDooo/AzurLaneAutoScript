from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from module.interaction.model import Action, ActionReceipt, AppStatus, Frame


class CancellationSignal(Protocol):
    def raise_if_requested(self) -> None: ...


class FrameSource(Protocol):
    def capture(self, cancellation: CancellationSignal) -> Frame: ...


class ActionSink(Protocol):
    def perform(self, action: Action, cancellation: CancellationSignal) -> ActionReceipt: ...


class AppLifecycle(Protocol):
    def status(self, cancellation: CancellationSignal) -> AppStatus: ...

    def start(self, cancellation: CancellationSignal) -> None: ...

    def stop(self, cancellation: CancellationSignal) -> None: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...

    def sleep(self, seconds: float, cancellation: CancellationSignal) -> None: ...


class Recognizer[ObservationT](Protocol):
    def observe(self, frame: Frame) -> ObservationT: ...
