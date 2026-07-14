from collections.abc import Iterable

from module.content.errors import ContentCatalogError, UnknownPackError, UnknownStageError
from module.content.models import EventPack, StageRef, StageSpec


class ContentCatalog:
    __slots__ = ("_packs", "_packs_by_id", "_stages_by_ref")

    def __init__(self, packs: Iterable[EventPack] = ()) -> None:
        if not isinstance(packs, Iterable):
            message = "packs must be iterable"
            raise TypeError(message)
        self._packs = tuple(packs)
        self._packs_by_id: dict[str, EventPack] = {}
        self._stages_by_ref: dict[StageRef, StageSpec] = {}

        for pack in self._packs:
            if not isinstance(pack, EventPack):
                message = "packs must contain EventPack instances"
                raise TypeError(message)
            pack_id = str(pack.pack_id)
            if pack_id in self._packs_by_id:
                message = f"duplicate pack id: {pack_id}"
                raise ContentCatalogError(message)
            self._packs_by_id[pack_id] = pack

            stage_ids: set[str] = set()
            for stage in pack.stages:
                if not isinstance(stage, StageSpec):
                    message = f"pack {pack_id} stages must contain StageSpec instances"
                    raise TypeError(message)
                if stage.ref.pack_id != pack_id:
                    message = f"stage {stage.ref.pack_id}/{stage.ref.stage_id} does not belong to pack {pack_id}"
                    raise ContentCatalogError(message)
                if stage.ref.stage_id in stage_ids:
                    message = f"duplicate stage id in pack {pack_id}: {stage.ref.stage_id}"
                    raise ContentCatalogError(message)
                stage_ids.add(stage.ref.stage_id)
                self._stages_by_ref[stage.ref] = stage

    @property
    def packs(self) -> tuple[EventPack, ...]:
        return self._packs

    @property
    def stages(self) -> tuple[StageSpec, ...]:
        return tuple(self._stages_by_ref.values())

    def get_pack(self, pack_id: str) -> EventPack:
        try:
            return self._packs_by_id[pack_id]
        except KeyError:
            message = f"unknown content pack: {pack_id}"
            raise UnknownPackError(message) from None

    def has_stage(self, ref: StageRef) -> bool:
        if not isinstance(ref, StageRef):
            message = "ref must be a StageRef"
            raise TypeError(message)
        pack = self._packs_by_id.get(ref.pack_id)
        if pack is None:
            return False
        canonical_ref = StageRef(ref.pack_id, pack.policy.resolve_alias(ref.stage_id))
        return canonical_ref in self._stages_by_ref

    def resolve_stage(self, ref: StageRef) -> StageSpec:
        if not isinstance(ref, StageRef):
            message = "ref must be a StageRef"
            raise TypeError(message)
        pack = self.get_pack(ref.pack_id)
        canonical_ref = StageRef(ref.pack_id, pack.policy.resolve_alias(ref.stage_id))
        try:
            return self._stages_by_ref[canonical_ref]
        except KeyError:
            message = f"unknown stage: {ref.pack_id}/{ref.stage_id}"
            raise UnknownStageError(message) from None

    def next_ref(self, ref: StageRef) -> StageRef | None:
        selected = self.resolve_stage(ref)
        pack = self.get_pack(selected.ref.pack_id)
        next_stage = pack.policy.next_stage(selected.ref.stage_id)
        if next_stage is None:
            return None
        next_ref = StageRef(selected.ref.pack_id, next_stage)
        if next_ref not in self._stages_by_ref:
            message = f"progression target is not registered: {next_ref.pack_id}/{next_ref.stage_id}"
            raise ContentCatalogError(message)
        return next_ref
