from typing import Literal, TypeIs

from module.exception import CampaignNameError, ScriptError

type CoalitionEvent = Literal[
    "coalition_20230323",
    "coalition_20240627",
    "coalition_20250626",
    "coalition_20251120",
    "coalition_20260122",
]
type CoalitionStage = Literal[
    "tc1",
    "tc2",
    "tc3",
    "easy",
    "normal",
    "hard",
    "sp",
    "ex",
    "area1-normal",
    "area2-normal",
    "area3-normal",
    "area4-normal",
    "area5-normal",
    "area6-normal",
    "area1-hard",
    "area2-hard",
    "area3-hard",
    "area4-hard",
    "area5-hard",
    "area6-hard",
]
type CoalitionFleetMode = Literal["single", "multi"]
type CoalitionPageMode = Literal["story", "battle"]
type CoalitionPageState = CoalitionPageMode | Literal["unknown"]

COALITION_EVENTS: tuple[CoalitionEvent, ...] = (
    "coalition_20230323",
    "coalition_20240627",
    "coalition_20250626",
    "coalition_20251120",
    "coalition_20260122",
)
COALITION_STAGES: tuple[CoalitionStage, ...] = (
    "tc1",
    "tc2",
    "tc3",
    "easy",
    "normal",
    "hard",
    "sp",
    "ex",
    "area1-normal",
    "area2-normal",
    "area3-normal",
    "area4-normal",
    "area5-normal",
    "area6-normal",
    "area1-hard",
    "area2-hard",
    "area3-hard",
    "area4-hard",
    "area5-hard",
    "area6-hard",
)


def _is_coalition_event(value: str) -> TypeIs[CoalitionEvent]:
    return value in COALITION_EVENTS


def _is_coalition_stage(value: str) -> TypeIs[CoalitionStage]:
    return value in COALITION_STAGES


def _is_coalition_fleet_mode(value: str) -> TypeIs[CoalitionFleetMode]:
    return value in ("single", "multi")


def parse_coalition_event(value: str) -> CoalitionEvent:
    if _is_coalition_event(value):
        return value
    message = f"Unsupported coalition event: {value}"
    raise ScriptError(message)


def parse_coalition_stage(value: str) -> CoalitionStage:
    if _is_coalition_stage(value):
        return value
    raise CampaignNameError(value)


def parse_coalition_fleet_mode(value: str) -> CoalitionFleetMode:
    if _is_coalition_fleet_mode(value):
        return value
    message = f"Unsupported coalition fleet mode: {value}"
    raise ScriptError(message)
