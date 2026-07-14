from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TypedDict, Unpack

from module.base.button import Button
from module.content.activity_catalog import RaidActivity
from module.content.activity_profile import RaidMode, RaidProfileId
from module.content.errors import ContentValidationError
from module.ocr.ocr import Digit, DigitCounter, OcrOptions
from module.raid import assets as raid_assets
from module.raid.ocr import (
    CompactRaidCounter,
    HuanChangPointOcr,
    HuanChangRemainCounter,
    PaddedRaidCounter,
)
from module.ui.assets import RAID_CHECK
from module.ui.page import Page, page_raid, page_rpg_stage


class RaidNavigationStrategy(StrEnum):
    STANDARD = "standard"
    RPG_CAROUSEL = "rpg_carousel"


class RaidAttemptSource(StrEnum):
    METERED = "metered"
    UNMETERED = "unmetered"


@dataclass(frozen=True, slots=True)
class CounterOcrSpec:
    region: Button
    counter_type: type[DigitCounter] = DigitCounter
    letter: tuple[int, int, int] = (255, 255, 255)
    threshold: int = 128
    lang: str = "azur_lane"
    alphabet: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.region, Button):
            message = "counter OCR region must be a Button"
            raise TypeError(message)
        if not isinstance(self.counter_type, type) or not issubclass(self.counter_type, DigitCounter):
            message = "counter_type must be a DigitCounter subclass"
            raise TypeError(message)

    def create(self) -> DigitCounter:
        options: OcrOptions = {
            "letter": self.letter,
            "threshold": self.threshold,
            "lang": self.lang,
            "alphabet": self.alphabet,
        }
        return self.counter_type(self.region, options)


@dataclass(frozen=True, slots=True)
class DigitOcrSpec:
    region: Button
    counter_type: type[Digit] = Digit
    letter: tuple[int, int, int] = (255, 255, 255)
    threshold: int = 128
    lang: str = "azur_lane"
    alphabet: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.region, Button):
            message = "digit OCR region must be a Button"
            raise TypeError(message)
        if not isinstance(self.counter_type, type) or not issubclass(self.counter_type, Digit):
            message = "counter_type must be a Digit subclass"
            raise TypeError(message)

    def create(self) -> Digit:
        options: OcrOptions = {
            "letter": self.letter,
            "threshold": self.threshold,
            "lang": self.lang,
            "alphabet": self.alphabet,
        }
        return self.counter_type(self.region, options)


type RaidRemainOcrSpec = CounterOcrSpec | DigitOcrSpec


@dataclass(frozen=True, slots=True)
class RaidModeClientProfile:
    mode: RaidMode
    entrance: Button
    attempt_source: RaidAttemptSource
    remain_ocr: RaidRemainOcrSpec | None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RaidMode):
            message = "mode must be a RaidMode"
            raise TypeError(message)
        if not isinstance(self.entrance, Button):
            message = "entrance must be a Button"
            raise TypeError(message)
        if not isinstance(self.attempt_source, RaidAttemptSource):
            message = "attempt_source must be a RaidAttemptSource"
            raise TypeError(message)
        if self.attempt_source is RaidAttemptSource.METERED and not isinstance(
            self.remain_ocr, CounterOcrSpec | DigitOcrSpec
        ):
            message = f"metered raid mode {self.mode.value!r} must define remain OCR"
            raise ContentValidationError(message)
        if self.attempt_source is RaidAttemptSource.UNMETERED and self.remain_ocr is not None:
            message = f"unmetered raid mode {self.mode.value!r} must not define remain OCR"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class RaidClientProfile:
    profile_id: RaidProfileId
    navigation: RaidNavigationStrategy
    landing_page: Page
    end_check: Button
    modes: tuple[RaidModeClientProfile, ...]
    point_ocr: DigitOcrSpec | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, RaidProfileId):
            message = "profile_id must be a RaidProfileId"
            raise TypeError(message)
        if not isinstance(self.navigation, RaidNavigationStrategy):
            message = "navigation must be a RaidNavigationStrategy"
            raise TypeError(message)
        if not isinstance(self.landing_page, Page):
            message = "landing_page must be a Page"
            raise TypeError(message)
        if not isinstance(self.end_check, Button):
            message = "end_check must be a Button"
            raise TypeError(message)
        if not isinstance(self.modes, tuple) or not self.modes:
            message = "modes must be a non-empty tuple"
            raise TypeError(message)
        if any(not isinstance(mode, RaidModeClientProfile) for mode in self.modes):
            message = "modes must contain RaidModeClientProfile values"
            raise TypeError(message)
        mode_ids = tuple(mode.mode for mode in self.modes)
        if len(set(mode_ids)) != len(mode_ids):
            message = f"duplicate mode in raid profile {self.profile_id.value!r}"
            raise ContentValidationError(message)
        if self.point_ocr is not None and not isinstance(self.point_ocr, DigitOcrSpec):
            message = "point_ocr must be a DigitOcrSpec or None"
            raise TypeError(message)

    def mode(self, mode: RaidMode) -> RaidModeClientProfile | None:
        if not isinstance(mode, RaidMode):
            message = "mode must be a RaidMode"
            raise TypeError(message)
        return next((item for item in self.modes if item.mode is mode), None)


class UnknownRaidProfileError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedRaidProfile:
    activity: RaidActivity
    client: RaidClientProfile

    def __post_init__(self) -> None:
        if not isinstance(self.activity, RaidActivity):
            message = "activity must be a RaidActivity"
            raise TypeError(message)
        if not isinstance(self.client, RaidClientProfile):
            message = "client must be a RaidClientProfile"
            raise TypeError(message)
        if self.activity.definition.profile_id != self.client.profile_id:
            message = "raid activity and client profile ids must match"
            raise ContentValidationError(message)

        content_modes = frozenset(self.activity.definition.modes)
        client_modes = frozenset(mode.mode for mode in self.client.modes)
        if content_modes != client_modes:
            missing = sorted(mode.value for mode in content_modes - client_modes)
            extra = sorted(mode.value for mode in client_modes - content_modes)
            message = f"raid profile {self.client.profile_id.value!r} mode mismatch: missing={missing}, extra={extra}"
            raise ContentValidationError(message)

        metered_modes = frozenset(
            mode.mode for mode in self.client.modes if mode.attempt_source is RaidAttemptSource.METERED
        )
        required_metered = frozenset((*self.activity.definition.daily_modes, *self.activity.definition.ticket_modes))
        if not required_metered.issubset(metered_modes):
            missing = sorted(mode.value for mode in required_metered - metered_modes)
            message = f"raid daily/ticket modes must have remain OCR: {missing}"
            raise ContentValidationError(message)

    def plan(self, mode: RaidMode, *, use_ticket: bool = False) -> RaidRunPlan:
        return RaidRunPlan(profile=self, mode=mode, use_ticket=use_ticket)

    def daily_plan(self, mode: RaidMode, *, use_ticket: bool = False) -> RaidRunPlan:
        if not isinstance(mode, RaidMode):
            message = "mode must be a RaidMode"
            raise TypeError(message)
        if mode not in self.activity.definition.daily_modes:
            message = f"raid mode {mode.value!r} is not daily content"
            raise ContentValidationError(message)
        return self.plan(mode, use_ticket=use_ticket)


@dataclass(frozen=True, slots=True)
class RaidRunPlan:
    profile: ResolvedRaidProfile
    mode: RaidMode
    use_ticket: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ResolvedRaidProfile):
            message = "profile must be a ResolvedRaidProfile"
            raise TypeError(message)
        if not isinstance(self.mode, RaidMode):
            message = "mode must be a RaidMode"
            raise TypeError(message)
        if type(self.use_ticket) is not bool:
            message = "use_ticket must be a bool"
            raise TypeError(message)
        if self.mode not in self.profile.activity.definition.modes:
            message = f"raid mode {self.mode.value!r} is not supported by selected content"
            raise ContentValidationError(message)
        if self.use_ticket and self.mode not in self.profile.activity.definition.ticket_modes:
            message = f"raid tickets are not supported in mode {self.mode.value!r}"
            raise ContentValidationError(message)

    @property
    def mode_profile(self) -> RaidModeClientProfile:
        mode = self.profile.client.mode(self.mode)
        if mode is None:
            message = f"raid client profile does not define mode {self.mode.value!r}"
            raise ContentValidationError(message)
        return mode


class RaidClientProfileRegistry:
    __slots__ = ("_profiles",)

    def __init__(self, profiles: Iterable[RaidClientProfile]) -> None:
        if not isinstance(profiles, Iterable):
            message = "profiles must be iterable"
            raise TypeError(message)
        indexed: dict[RaidProfileId, RaidClientProfile] = {}
        for profile in profiles:
            if not isinstance(profile, RaidClientProfile):
                message = "profiles must contain RaidClientProfile values"
                raise TypeError(message)
            if profile.profile_id in indexed:
                message = f"duplicate raid client profile: {profile.profile_id.value}"
                raise ContentValidationError(message)
            indexed[profile.profile_id] = profile
        self._profiles = MappingProxyType(indexed)

    @property
    def profile_ids(self) -> frozenset[RaidProfileId]:
        return frozenset(self._profiles)

    def resolve(self, profile_id: RaidProfileId) -> RaidClientProfile:
        if not isinstance(profile_id, RaidProfileId):
            message = "profile_id must be a RaidProfileId"
            raise TypeError(message)
        try:
            return self._profiles[profile_id]
        except KeyError:
            message = f"unknown raid client profile: {profile_id.value}"
            raise UnknownRaidProfileError(message) from None

    def bind(self, activity: RaidActivity) -> ResolvedRaidProfile:
        if not isinstance(activity, RaidActivity):
            message = "activity must be a RaidActivity"
            raise TypeError(message)
        return ResolvedRaidProfile(activity=activity, client=self.resolve(activity.definition.profile_id))


class _CounterOcrOptions(TypedDict, total=False):
    counter_type: type[DigitCounter]
    letter: tuple[int, int, int]
    threshold: int
    lang: str
    alphabet: str | None


def _metered_counter(
    mode: RaidMode,
    entrance: Button,
    region: Button,
    **options: Unpack[_CounterOcrOptions],
) -> RaidModeClientProfile:
    return RaidModeClientProfile(
        mode=mode,
        entrance=entrance,
        attempt_source=RaidAttemptSource.METERED,
        remain_ocr=CounterOcrSpec(region=region, **options),
    )


def _metered_digit(
    mode: RaidMode,
    entrance: Button,
    region: Button,
    *,
    letter: tuple[int, int, int] = (255, 255, 255),
    threshold: int = 128,
) -> RaidModeClientProfile:
    return RaidModeClientProfile(
        mode=mode,
        entrance=entrance,
        attempt_source=RaidAttemptSource.METERED,
        remain_ocr=DigitOcrSpec(region=region, letter=letter, threshold=threshold),
    )


def _unmetered(mode: RaidMode, entrance: Button) -> RaidModeClientProfile:
    return RaidModeClientProfile(
        mode=mode,
        entrance=entrance,
        attempt_source=RaidAttemptSource.UNMETERED,
        remain_ocr=None,
    )


def _standard_profile(
    profile_id: str,
    modes: tuple[RaidModeClientProfile, ...],
    *,
    point_ocr: DigitOcrSpec | None = None,
) -> RaidClientProfile:
    return RaidClientProfile(
        profile_id=RaidProfileId(profile_id),
        navigation=RaidNavigationStrategy.STANDARD,
        landing_page=page_raid,
        end_check=RAID_CHECK,
        modes=modes,
        point_ocr=point_ocr,
    )


ESSEX_RAID_PROFILE = _standard_profile(
    "essex",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.ESSEX_RAID_EASY,
            raid_assets.ESSEX_OCR_REMAIN_EASY,
            counter_type=PaddedRaidCounter,
            letter=(57, 52, 255),
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.ESSEX_RAID_NORMAL,
            raid_assets.ESSEX_OCR_REMAIN_NORMAL,
            counter_type=PaddedRaidCounter,
            letter=(57, 52, 255),
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.ESSEX_RAID_HARD,
            raid_assets.ESSEX_OCR_REMAIN_HARD,
            counter_type=PaddedRaidCounter,
            letter=(57, 52, 255),
        ),
    ),
)

SURUGA_RAID_PROFILE = _standard_profile(
    "suruga",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.SURUGA_RAID_EASY,
            raid_assets.SURUGA_OCR_REMAIN_EASY,
            counter_type=PaddedRaidCounter,
            letter=(49, 48, 49),
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.SURUGA_RAID_NORMAL,
            raid_assets.SURUGA_OCR_REMAIN_NORMAL,
            counter_type=PaddedRaidCounter,
            letter=(49, 48, 49),
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.SURUGA_RAID_HARD,
            raid_assets.SURUGA_OCR_REMAIN_HARD,
            counter_type=PaddedRaidCounter,
            letter=(49, 48, 49),
        ),
    ),
)

BRISTOL_RAID_PROFILE = _standard_profile(
    "bristol",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.BRISTOL_RAID_EASY,
            raid_assets.BRISTOL_OCR_REMAIN_EASY,
            counter_type=PaddedRaidCounter,
            letter=(214, 231, 219),
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.BRISTOL_RAID_NORMAL,
            raid_assets.BRISTOL_OCR_REMAIN_NORMAL,
            counter_type=PaddedRaidCounter,
            letter=(214, 231, 219),
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.BRISTOL_RAID_HARD,
            raid_assets.BRISTOL_OCR_REMAIN_HARD,
            counter_type=PaddedRaidCounter,
            letter=(214, 231, 219),
        ),
    ),
)

IRIS_RAID_PROFILE = _standard_profile(
    "iris",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.IRIS_RAID_EASY,
            raid_assets.IRIS_OCR_REMAIN_EASY,
            letter=(148, 138, 123),
            lang="cnocr",
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.IRIS_RAID_NORMAL,
            raid_assets.IRIS_OCR_REMAIN_NORMAL,
            letter=(148, 138, 123),
            lang="cnocr",
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.IRIS_RAID_HARD,
            raid_assets.IRIS_OCR_REMAIN_HARD,
            letter=(148, 138, 123),
            lang="cnocr",
        ),
    ),
    point_ocr=DigitOcrSpec(region=raid_assets.IRIS_OCR_PT, letter=(181, 178, 165)),
)

ALBION_RAID_PROFILE = _standard_profile(
    "albion",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.ALBION_RAID_EASY,
            raid_assets.ALBION_OCR_REMAIN_EASY,
            letter=(99, 73, 57),
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.ALBION_RAID_NORMAL,
            raid_assets.ALBION_OCR_REMAIN_NORMAL,
            letter=(99, 73, 57),
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.ALBION_RAID_HARD,
            raid_assets.ALBION_OCR_REMAIN_HARD,
            letter=(99, 73, 57),
        ),
    ),
    point_ocr=DigitOcrSpec(region=raid_assets.ALBION_OCR_PT, letter=(23, 20, 9)),
)

KUYBYSHEY_RAID_PROFILE = _standard_profile(
    "kuybyshey",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.KUYBYSHEY_RAID_EASY,
            raid_assets.KUYBYSHEY_OCR_REMAIN_EASY,
            letter=(231, 239, 247),
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.KUYBYSHEY_RAID_NORMAL,
            raid_assets.KUYBYSHEY_OCR_REMAIN_NORMAL,
            letter=(231, 239, 247),
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.KUYBYSHEY_RAID_HARD,
            raid_assets.KUYBYSHEY_OCR_REMAIN_HARD,
            letter=(231, 239, 247),
        ),
        _metered_digit(
            RaidMode.EX,
            raid_assets.KUYBYSHEY_RAID_EX,
            raid_assets.KUYBYSHEY_OCR_REMAIN_EX,
            letter=(189, 203, 214),
        ),
    ),
    point_ocr=DigitOcrSpec(region=raid_assets.KUYBYSHEY_OCR_PT, letter=(16, 24, 33), threshold=64),
)

GORIZIA_RAID_PROFILE = _standard_profile(
    "gorizia",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.GORIZIA_RAID_EASY,
            raid_assets.GORIZIA_OCR_REMAIN_EASY,
            letter=(82, 89, 66),
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.GORIZIA_RAID_NORMAL,
            raid_assets.GORIZIA_OCR_REMAIN_NORMAL,
            letter=(82, 89, 66),
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.GORIZIA_RAID_HARD,
            raid_assets.GORIZIA_OCR_REMAIN_HARD,
            letter=(82, 89, 66),
        ),
        _metered_digit(
            RaidMode.EX,
            raid_assets.GORIZIA_RAID_EX,
            raid_assets.GORIZIA_OCR_REMAIN_EX,
            letter=(198, 223, 140),
        ),
    ),
    point_ocr=DigitOcrSpec(region=raid_assets.GORIZIA_OCR_PT, threshold=64),
)

HUANCHANG_RAID_PROFILE = _standard_profile(
    "huanchang",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.HUANCHANG_RAID_EASY,
            raid_assets.HUANCHANG_OCR_REMAIN_EASY,
            counter_type=HuanChangRemainCounter,
            threshold=80,
            alphabet="0123456789IDSB",
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.HUANCHANG_RAID_NORMAL,
            raid_assets.HUANCHANG_OCR_REMAIN_NORMAL,
            counter_type=HuanChangRemainCounter,
            threshold=80,
            alphabet="0123456789IDSB",
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.HUANCHANG_RAID_HARD,
            raid_assets.HUANCHANG_OCR_REMAIN_HARD,
            counter_type=HuanChangRemainCounter,
            threshold=80,
            alphabet="0123456789IDSB",
        ),
        _metered_digit(
            RaidMode.EX,
            raid_assets.HUANCHANG_RAID_EX,
            raid_assets.HUANCHANG_OCR_REMAIN_EX,
            threshold=180,
        ),
    ),
    point_ocr=DigitOcrSpec(
        region=raid_assets.HUANCHANG_OCR_PT,
        counter_type=HuanChangPointOcr,
        letter=(23, 20, 6),
    ),
)

RPG_RAID_PROFILE = RaidClientProfile(
    profile_id=RaidProfileId("rpg"),
    navigation=RaidNavigationStrategy.RPG_CAROUSEL,
    landing_page=page_rpg_stage,
    end_check=raid_assets.RPG_GOTO_STORY,
    modes=(
        _unmetered(RaidMode.EASY, raid_assets.RPG_RAID_EASY),
        _unmetered(RaidMode.NORMAL, raid_assets.RPG_RAID_NORMAL),
        _unmetered(RaidMode.HARD, raid_assets.RPG_RAID_HARD),
        _unmetered(RaidMode.EX, raid_assets.RPG_RAID_EX),
    ),
)

CHIENWU_RAID_PROFILE = _standard_profile(
    "chienwu",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.CHIENWU_RAID_EASY,
            raid_assets.CHIENWU_OCR_REMAIN_EASY,
            letter=(0, 0, 0),
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.CHIENWU_RAID_NORMAL,
            raid_assets.CHIENWU_OCR_REMAIN_NORMAL,
            letter=(0, 0, 0),
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.CHIENWU_RAID_HARD,
            raid_assets.CHIENWU_OCR_REMAIN_HARD,
            letter=(0, 0, 0),
        ),
        _metered_digit(
            RaidMode.EX,
            raid_assets.CHIENWU_RAID_EX,
            raid_assets.CHIENWU_OCR_REMAIN_EX,
            letter=(247, 223, 222),
        ),
    ),
    point_ocr=DigitOcrSpec(region=raid_assets.CHIENWU_OCR_PT, letter=(255, 231, 231)),
)

CHANGWU_RAID_PROFILE = _standard_profile(
    "changwu",
    (
        _metered_counter(
            RaidMode.EASY,
            raid_assets.CHANGWU_RAID_EASY,
            raid_assets.CHANGWU_OCR_REMAIN_EASY,
            counter_type=CompactRaidCounter,
            letter=(154, 148, 133),
            lang="cnocr",
        ),
        _metered_counter(
            RaidMode.NORMAL,
            raid_assets.CHANGWU_RAID_NORMAL,
            raid_assets.CHANGWU_OCR_REMAIN_NORMAL,
            counter_type=CompactRaidCounter,
            letter=(154, 148, 133),
            lang="cnocr",
        ),
        _metered_counter(
            RaidMode.HARD,
            raid_assets.CHANGWU_RAID_HARD,
            raid_assets.CHANGWU_OCR_REMAIN_HARD,
            counter_type=CompactRaidCounter,
            letter=(154, 148, 133),
            lang="cnocr",
        ),
        _metered_digit(
            RaidMode.EX,
            raid_assets.CHANGWU_RAID_EX,
            raid_assets.CHANGWU_OCR_REMAIN_EX,
            letter=(255, 239, 215),
        ),
    ),
    point_ocr=DigitOcrSpec(region=raid_assets.CHANGWU_OCR_PT, letter=(255, 239, 215)),
)


RAID_CLIENT_PROFILES = RaidClientProfileRegistry(
    (
        ESSEX_RAID_PROFILE,
        SURUGA_RAID_PROFILE,
        BRISTOL_RAID_PROFILE,
        IRIS_RAID_PROFILE,
        ALBION_RAID_PROFILE,
        KUYBYSHEY_RAID_PROFILE,
        GORIZIA_RAID_PROFILE,
        HUANCHANG_RAID_PROFILE,
        RPG_RAID_PROFILE,
        CHIENWU_RAID_PROFILE,
        CHANGWU_RAID_PROFILE,
    )
)
