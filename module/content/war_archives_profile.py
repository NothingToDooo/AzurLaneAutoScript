import re
from dataclasses import dataclass

from module.content.errors import ContentValidationError

_PROFILE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)


@dataclass(frozen=True, slots=True, order=True)
class WarArchivesProfileId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            message = "war archives profile id must be a string"
            raise TypeError(message)
        if _PROFILE_ID_PATTERN.fullmatch(self.value) is None:
            message = "war archives profile id must be a canonical identifier"
            raise ContentValidationError(message)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class WarArchivesDefinition:
    profile_id: WarArchivesProfileId

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, WarArchivesProfileId):
            message = "profile_id must be a WarArchivesProfileId"
            raise TypeError(message)
