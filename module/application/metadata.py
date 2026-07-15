from dataclasses import dataclass


def _validate_revision(revision: str, *, field: str) -> None:
    if not isinstance(revision, str):
        message = f"{field} must be a string"
        raise TypeError(message)
    if not revision or revision != revision.strip():
        message = f"{field} must not be empty or contain surrounding whitespace"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class RunMetadata:
    settings_revision: int
    content_revision: str

    def __post_init__(self) -> None:
        if type(self.settings_revision) is not int:
            message = "settings_revision must be an integer"
            raise TypeError(message)
        if self.settings_revision <= 0:
            message = "settings_revision must be positive"
            raise ValueError(message)
        _validate_revision(self.content_revision, field="content_revision")
