from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from module.base.template import Template
from module.content.war_archives_profile import WarArchivesProfileId
from module.war_archives import assets as wa_assets


class WarArchivesClientProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WarArchivesClientProfile:
    profile_id: WarArchivesProfileId
    entrance: Template

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, WarArchivesProfileId):
            message = "profile_id must be a WarArchivesProfileId"
            raise TypeError(message)
        if not isinstance(self.entrance, Template):
            message = "entrance must be a Template"
            raise TypeError(message)


class WarArchivesClientProfileRegistry:
    __slots__ = ("_profiles",)

    def __init__(self, profiles: Iterable[WarArchivesClientProfile]) -> None:
        if not isinstance(profiles, Iterable):
            message = "profiles must be iterable"
            raise TypeError(message)
        indexed: dict[WarArchivesProfileId, WarArchivesClientProfile] = {}
        for profile in profiles:
            if not isinstance(profile, WarArchivesClientProfile):
                message = "profiles must contain WarArchivesClientProfile values"
                raise TypeError(message)
            if profile.profile_id in indexed:
                message = f"duplicate war archives client profile: {profile.profile_id.value}"
                raise WarArchivesClientProfileError(message)
            indexed[profile.profile_id] = profile
        if not indexed:
            message = "war archives client profile registry must not be empty"
            raise WarArchivesClientProfileError(message)
        self._profiles: Mapping[WarArchivesProfileId, WarArchivesClientProfile] = MappingProxyType(indexed)

    @property
    def profiles(self) -> tuple[WarArchivesClientProfile, ...]:
        return tuple(self._profiles.values())

    def resolve(self, profile_id: WarArchivesProfileId) -> WarArchivesClientProfile:
        if not isinstance(profile_id, WarArchivesProfileId):
            message = "profile_id must be a WarArchivesProfileId"
            raise TypeError(message)
        try:
            return self._profiles[profile_id]
        except KeyError:
            message = f"unknown war archives client profile: {profile_id.value}"
            raise WarArchivesClientProfileError(message) from None


def _profile(profile_id: str, entrance: Template) -> WarArchivesClientProfile:
    return WarArchivesClientProfile(WarArchivesProfileId(profile_id), entrance)


WAR_ARCHIVES_CLIENT_PROFILES = WarArchivesClientProfileRegistry(
    (
        _profile("visitors_dyed_in_red", wa_assets.TEMPLATE_VISITORS_DYED_IN_RED),
        _profile("fallen_wings", wa_assets.TEMPLATE_FALLEN_WINGS),
        _profile("winters_crown", wa_assets.TEMPLATE_WINTERS_CROWN),
        _profile("divergent_chessboard", wa_assets.TEMPLATE_DIVERGENT_CHESSBOARD),
        _profile("strive_wish_and_strategize", wa_assets.TEMPLATE_STRIVE_WISH_AND_STRATEGIZE),
        _profile("encircling_graf_spee", wa_assets.TEMPLATE_ENCIRCLING_GRAF_SPEE),
        _profile("glorious_battle", wa_assets.TEMPLATE_GLORIOUS_BATTLE),
        _profile("ink_stained_steel_sakura", wa_assets.TEMPLATE_INK_STAINED_STEEL_SAKURA),
        _profile("iris_of_light_and_dark", wa_assets.TEMPLATE_IRIS_OF_LIGHT_AND_DARK),
        _profile("crimson_echoes", wa_assets.TEMPLATE_CRIMSON_ECHOES),
        _profile("scherzo_of_iron_and_blood", wa_assets.TEMPLATE_SCHERZO_OF_IRON_AND_BLOOD),
        _profile("crescendo_of_polaris", wa_assets.TEMPLATE_CRESCENDO_OF_POLARIS),
        _profile("empyreal_tragicomedy", wa_assets.TEMPLATE_EMPYREAL_TRAGICOMEDY),
        _profile("ashen_simulacrum", wa_assets.TEMPLATE_ASHEN_SIMULACRUM),
        _profile("swirling_cherry_blossoms", wa_assets.TEMPLATE_SWIRLING_CHERRY_BLOSSOMS),
        _profile("skybound_oratorio", wa_assets.TEMPLATE_SKYBOUND_ORATORIO),
        _profile("the_enigma_and_the_shark", wa_assets.TEMPLATE_THE_ENIGMA_AND_THE_SHARK),
        _profile("universe_in_unison", wa_assets.TEMPLATE_UNIVERSE_IN_UNISON),
        _profile("stars_of_the_shimmering_fjord", wa_assets.TEMPLATE_STARS_OF_THE_SHIMMERING_FJORD),
        _profile("microlayer_medley", wa_assets.TEMPLATE_MICROLAYER_MEDLEY),
        _profile("northern_overture", wa_assets.TEMPLATE_NORTHERN_OVERTURE),
        _profile("aurora_noctis", wa_assets.TEMPLATE_AURORA_NOCTIS),
        _profile("inverted_orthant", wa_assets.TEMPLATE_INVERTED_ORTHANT),
        _profile("dreamwakers_butterfly", wa_assets.TEMPLATE_DREAMWAKERS_BUTTERFLY),
        _profile("mirror_involution", wa_assets.TEMPLATE_MIRROR_INVOLUTION),
        _profile("khorovod_of_dawns_rime", wa_assets.TEMPLATE_KHOROVOD_OF_DAWNS_RIME),
        _profile("counterattack_within_the_fjord", wa_assets.TEMPLATE_COUNTERATTACK_WITHIN_THE_FJORD),
        _profile("prelude_under_the_moon", wa_assets.TEMPLATE_PRELUDE_UNDER_THE_MOON),
        _profile("the_solomon_ranger", wa_assets.TEMPLATE_THE_SOLOMON_RANGER),
        _profile("the_way_home_in_the_night", wa_assets.TEMPLATE_THE_WAY_HOME_IN_THE_NIGHT),
        _profile("sundered_blue", wa_assets.TEMPLATE_SUNDERED_BLUE),
        _profile("the_flame_touched_dagger", wa_assets.TEMPLATE_THE_FLAME_TOUCHED_DAGGER),
        _profile("upon_the_shimmering_blue", wa_assets.TEMPLATE_UPON_THE_SHIMMERING_BLUE),
        _profile("daedalian_hymn", wa_assets.TEMPLATE_DAEDALIAN_HYMN),
        _profile("tower_of_transcendence", wa_assets.TEMPLATE_TOWER_OF_TRANSCENDENCE),
        _profile("abyssal_refrain", wa_assets.TEMPLATE_ABYSSAL_REFRAIN),
        _profile("virtual_tower", wa_assets.TEMPLATE_VIRTUAL_TOWER),
        _profile("pledge_of_the_radiant_court", wa_assets.TEMPLATE_PLEDGE_OF_THE_RADIANT_COURT),
        _profile("aquilifers_ballade", wa_assets.TEMPLATE_AQUILIFERS_BALLADE),
        _profile("rondo_at_rainbows_end", wa_assets.TEMPLATE_RONDO_AT_RAINBOWS_END),
        _profile(
            "tempesta_and_the_fountain_of_youth",
            wa_assets.TEMPLATE_TEMPESTA_AND_THE_FOUNTAIN_OF_YOUTH,
        ),
        _profile(
            "violet_tempest_blooming_lycoris",
            wa_assets.TEMPLATE_VIOLET_TEMPEST_BLOOMING_LYCORIS,
        ),
        _profile("parallel_superimposition", wa_assets.TEMPLATE_PARALLEL_SUPERIMPOSITION),
        _profile("revelations_of_dust", wa_assets.TEMPLATE_REVELATIONS_OF_DUST),
        _profile("operation_convergence", wa_assets.TEMPLATE_OPERATION_CONVERGENCE),
        _profile("anthem_of_remembrance", wa_assets.TEMPLATE_ANTHEM_OF_REMEMBRANCE),
        _profile("confluence_of_nothingness", wa_assets.TEMPLATE_CONFLUENCE_OF_NOTHINGNESS),
        _profile("interlude_of_illusions", wa_assets.TEMPLATE_INTERLUDE_OF_ILLUSIONS),
    )
)
