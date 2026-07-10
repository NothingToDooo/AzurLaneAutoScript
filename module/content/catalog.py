from typing import TYPE_CHECKING

from module.content.errors import ContentCatalogError, UnknownPackError, UnknownStageError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.content.models import EventPack, StageRef, StageSpec


class ContentCatalog:
    __slots__ = ("_packs_by_id", "_stages_by_ref", "packs")

    def __init__(self, packs: Iterable[EventPack] = ()) -> None:
        self.packs = tuple(packs)
        self._packs_by_id: dict[str, EventPack] = {}
        self._stages_by_ref: dict[StageRef, StageSpec] = {}

        for pack in self.packs:
            pack_id = str(pack.pack_id)
            if pack_id in self._packs_by_id:
                message = f"duplicate pack id: {pack_id}"
                raise ContentCatalogError(message)
            self._packs_by_id[pack_id] = pack

            stage_ids: set[str] = set()
            for stage in pack.stages:
                if stage.ref.pack_id != pack_id:
                    message = f"stage {stage.ref.pack_id}/{stage.ref.stage_id} does not belong to pack {pack_id}"
                    raise ContentCatalogError(message)
                if stage.ref.stage_id in stage_ids:
                    message = f"duplicate stage id in pack {pack_id}: {stage.ref.stage_id}"
                    raise ContentCatalogError(message)
                stage_ids.add(stage.ref.stage_id)
                self._stages_by_ref[stage.ref] = stage

    def get_pack(self, pack_id: str) -> EventPack:
        try:
            return self._packs_by_id[pack_id]
        except KeyError:
            message = f"unknown content pack: {pack_id}"
            raise UnknownPackError(message) from None

    def resolve_stage(self, ref: StageRef) -> StageSpec:
        self.get_pack(ref.pack_id)
        try:
            return self._stages_by_ref[ref]
        except KeyError:
            message = f"unknown stage: {ref.pack_id}/{ref.stage_id}"
            raise UnknownStageError(message) from None
