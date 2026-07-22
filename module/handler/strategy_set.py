from dataclasses import dataclass
from typing import Literal, Protocol, override

type StrategyFormation = Literal["line_ahead", "double_line", "diamond"]


@dataclass(frozen=True, slots=True)
class StrategySetRequest:
    formation: StrategyFormation | None = None
    sub_view: bool | None = None
    sub_hunt: bool | None = None

    def __post_init__(self) -> None:
        if self.formation not in (None, "line_ahead", "double_line", "diamond"):
            message = f"unsupported strategy formation: {self.formation!r}"
            raise ValueError(message)
        if self.sub_view is not None and type(self.sub_view) is not bool:
            message = "strategy sub_view must be a boolean or None"
            raise TypeError(message)
        if self.sub_hunt is not None and type(self.sub_hunt) is not bool:
            message = "strategy sub_hunt must be a boolean or None"
            raise TypeError(message)


class StrategySetRuntime(Protocol):
    def _standard_strategy_set_execute(self, request: StrategySetRequest) -> None: ...


class StrategySetService(Protocol):
    def execute(
        self,
        runtime: StrategySetRuntime,
        request: StrategySetRequest,
    ) -> None: ...


class _StandardStrategySetService(StrategySetService):
    @override
    def execute(
        self,
        runtime: StrategySetRuntime,
        request: StrategySetRequest,
    ) -> None:
        if not isinstance(request, StrategySetRequest):
            message = "strategy set service requires a StrategySetRequest"
            raise TypeError(message)
        runtime._standard_strategy_set_execute(  # ruff:ignore[private-member-access] - typed service owns this primitive.
            request
        )


STANDARD_STRATEGY_SET_SERVICE: StrategySetService = _StandardStrategySetService()
