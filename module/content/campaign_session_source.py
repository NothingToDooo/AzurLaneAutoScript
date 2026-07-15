from dataclasses import dataclass
from secrets import choice
from typing import TYPE_CHECKING

from module.content.campaign_session import CampaignRunVariant, CampaignSession
from module.content.catalog import ContentCatalog
from module.content.errors import ContentValidationError
from module.content.models import StageRef, StageSpec
from module.content.stage_definition import CampaignStageDefinition
from module.content.stage_loader import StageSpecLoader

type CampaignSessionKey = tuple[StageRef, CampaignRunVariant]

_HARD_CAMPAIGN_PACK = "campaign_hard"
_MAIN_CAMPAIGN_PACK = "campaign_main"

if TYPE_CHECKING:
    from collections.abc import Callable


def _validated_map_achievement_fallbacks(
    values: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    fallbacks = tuple((source, target) for source, target in values)
    if any(not isinstance(value, str) or not value for pair in fallbacks for value in pair):
        message = "map achievement fallbacks must contain non-empty strings"
        raise ContentValidationError(message)
    if len({source for source, _target in fallbacks}) != len(fallbacks):
        message = "map achievement fallback sources must be unique"
        raise ContentValidationError(message)
    return fallbacks


@dataclass(frozen=True, slots=True)
class CampaignStageSelection:
    """配置关卡经内容包 alias/loop policy 解析后的单次运行选择。"""

    requested_ref: StageRef
    selected_ref: StageRef
    loop_stage_switch: bool = False
    next_ref: StageRef | None = None
    force_threat_safe: bool = False
    resource_free: bool = False
    map_achievement_fallbacks: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.requested_ref, StageRef):
            message = "requested_ref must be a StageRef"
            raise TypeError(message)
        if not isinstance(self.selected_ref, StageRef):
            message = "selected_ref must be a StageRef"
            raise TypeError(message)
        if self.requested_ref.pack_id != self.selected_ref.pack_id:
            message = "campaign stage selection must stay inside one content pack"
            raise ContentValidationError(message)
        if type(self.loop_stage_switch) is not bool:
            message = "loop_stage_switch must be a boolean"
            raise TypeError(message)
        if self.next_ref is not None:
            if not isinstance(self.next_ref, StageRef):
                message = "next_ref must be a StageRef or None"
                raise TypeError(message)
            if self.next_ref.pack_id != self.selected_ref.pack_id or self.next_ref == self.selected_ref:
                message = "campaign progression must advance inside one content pack"
                raise ContentValidationError(message)
        if type(self.force_threat_safe) is not bool or type(self.resource_free) is not bool:
            message = "campaign stage policy flags must be booleans"
            raise TypeError(message)
        object.__setattr__(
            self,
            "map_achievement_fallbacks",
            _validated_map_achievement_fallbacks(self.map_achievement_fallbacks),
        )


class CompiledCampaignSessionSource:
    """按需编译关卡，并在当前进程内复用 definition 与 session。"""

    __slots__ = ("_catalog", "_definitions", "_loader", "_loop_choice", "_sessions")

    _catalog: ContentCatalog
    _loader: StageSpecLoader
    _loop_choice: Callable[[tuple[str, ...]], str]
    _definitions: dict[StageRef, CampaignStageDefinition]
    _sessions: dict[CampaignSessionKey, CampaignSession]

    def __init__(
        self,
        catalog: ContentCatalog,
        loader: StageSpecLoader,
        *,
        loop_choice: Callable[[tuple[str, ...]], str] = choice,
    ) -> None:
        if not isinstance(catalog, ContentCatalog):
            message = "catalog must be a ContentCatalog"
            raise TypeError(message)
        if not isinstance(loader, StageSpecLoader):
            message = "loader must be a StageSpecLoader"
            raise TypeError(message)
        if isinstance(loop_choice, type) or not callable(loop_choice):
            message = "loop_choice must be callable"
            raise TypeError(message)

        self._catalog = catalog
        self._loader = loader
        self._loop_choice = loop_choice
        self._definitions = {}
        self._sessions = {}

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def validate_all(self) -> None:
        """显式编译全部关卡；生产运行不调用此入口。"""

        for spec in self._catalog.stages:
            self._definition(spec)

    def _definition(self, spec: StageSpec) -> CampaignStageDefinition:
        cached = self._definitions.get(spec.ref)
        if cached is not None:
            return cached
        definition = self._loader.load(spec)
        self._validate_definition(spec, definition)
        self._definitions[spec.ref] = definition
        return definition

    @staticmethod
    def _validate_definition(spec: StageSpec, definition: CampaignStageDefinition) -> None:
        if not isinstance(definition, CampaignStageDefinition):
            message = "stage loader must return a CampaignStageDefinition"
            raise TypeError(message)
        if definition.ref != spec.ref:
            message = "stage loader returned a definition for a different StageRef"
            raise ContentValidationError(message)
        if definition.runtime_profile.profile_id != spec.runtime_profile_id:
            message = "stage loader returned a definition with a different runtime profile"
            raise ContentValidationError(message)
        if definition.war_archives != spec.war_archives:
            message = "stage loader returned a definition with a different war archives profile"
            raise ContentValidationError(message)

    def resolve(self, ref: StageRef, variant: CampaignRunVariant) -> CampaignSession:
        if not isinstance(ref, StageRef):
            message = "ref must be a StageRef"
            raise TypeError(message)
        if not isinstance(variant, CampaignRunVariant):
            message = "variant must be a CampaignRunVariant"
            raise TypeError(message)
        spec = self._catalog.resolve_stage(ref)
        key = (spec.ref, variant)
        cached = self._sessions.get(key)
        if cached is not None:
            return cached
        session = CampaignSession(self._definition(spec), variant)
        self._sessions[key] = session
        return session

    def resolve_hard_stage_ref(self, stage_id: str) -> StageRef:
        """困难图有显式内容定义时使用 override，否则使用同名主线图。"""

        if not isinstance(stage_id, str):
            message = "hard stage_id must be a string"
            raise TypeError(message)
        if not stage_id or stage_id != stage_id.strip():
            message = "hard stage_id must be trimmed and non-empty"
            raise ValueError(message)
        normalized_stage_id = stage_id.lower()
        hard_ref = StageRef(_HARD_CAMPAIGN_PACK, normalized_stage_id)
        if self._catalog.has_stage(hard_ref):
            return self._catalog.resolve_stage(hard_ref).ref
        return self._catalog.resolve_stage(StageRef(_MAIN_CAMPAIGN_PACK, normalized_stage_id)).ref

    def select(
        self,
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection:
        """解析普通 alias 或循环 alias；随机选择只发生一次，再由调用方解析两个 variant。"""

        if not isinstance(ref, StageRef):
            message = "ref must be a StageRef"
            raise TypeError(message)
        if type(remaining_runs) is not int or remaining_runs < 0:
            message = "remaining_runs must be a non-negative integer"
            raise ValueError(message)
        if preferred_ref is not None and not isinstance(preferred_ref, StageRef):
            message = "preferred_ref must be a StageRef or None"
            raise TypeError(message)

        pack = self._catalog.get_pack(ref.pack_id)
        aliased_stage = pack.policy.resolve_alias(ref.stage_id)
        loop_stages = pack.policy.loop_stages(aliased_stage)
        loop_stage_switch = loop_stages is not None
        candidate_stages = (aliased_stage,) if loop_stages is None else loop_stages
        candidate_refs = tuple(
            self._catalog.resolve_stage(StageRef(ref.pack_id, stage_id)).ref for stage_id in candidate_stages
        )
        if preferred_ref is not None:
            preferred = self._catalog.resolve_stage(preferred_ref).ref
            progression_candidates = self._progression_from(candidate_refs[0]) if len(candidate_refs) == 1 else ()
            if preferred not in candidate_refs and preferred not in progression_candidates:
                message = "preferred_ref is not a valid selection for the requested campaign stage"
                raise ContentValidationError(message)
            selected_ref = preferred
        elif loop_stages is None:
            selected_ref = candidate_refs[0]
        elif remaining_runs == 0:
            selected_stage = self._loop_choice(loop_stages)
            if selected_stage not in loop_stages:
                message = "loop_choice must return one of the declared loop stages"
                raise ContentValidationError(message)
            selected_ref = self._catalog.resolve_stage(StageRef(ref.pack_id, selected_stage)).ref
        else:
            cycle = len(loop_stages)
            index = remaining_runs % cycle
            index = 0 if index == 0 else cycle - index
            selected_ref = candidate_refs[index]

        selected_pack = self._catalog.get_pack(selected_ref.pack_id)
        return CampaignStageSelection(
            requested_ref=ref,
            selected_ref=selected_ref,
            loop_stage_switch=loop_stage_switch,
            next_ref=self._catalog.next_ref(selected_ref),
            force_threat_safe=selected_ref.stage_id in selected_pack.policy.force_threat_safe_stages,
            resource_free=selected_ref.stage_id in selected_pack.policy.resource_free_stages,
            map_achievement_fallbacks=selected_pack.policy.map_achievement_fallbacks,
        )

    def _progression_from(self, ref: StageRef) -> tuple[StageRef, ...]:
        progression: list[StageRef] = []
        seen = {ref}
        current = ref
        while True:
            next_ref = self._catalog.next_ref(current)
            if next_ref is None:
                return tuple(progression)
            if next_ref in seen:
                message = "campaign progression contains a cycle"
                raise ContentValidationError(message)
            seen.add(next_ref)
            progression.append(next_ref)
            current = next_ref
