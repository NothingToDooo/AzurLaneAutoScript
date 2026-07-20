from typing import Literal

type GridLocation = tuple[int, int]
type FleetLocation = GridLocation | tuple[()]
type GridMode = Literal["init", "normal", "carrier", "movable", "decoy"]
type ViewMode = Literal["main", "os"]
